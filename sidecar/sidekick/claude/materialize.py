"""Turn a brainstorm into a project folder: documents, git, and a Claude Code kickoff.

`Materializer.start()` runs a background job per brainstorm session and reports progress
as `materialize_progress` events. Documents are written by the docs model, one call per
file in parallel; a file that fails twice gets a placeholder so the rest still lands.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Settings
from ..db import Database, new_id, now_iso
from ..events import EventBus
from .idea import IdeaState, slugify
from .utility import load_prompt

log = logging.getLogger(__name__)

TRANSCRIPT_LIMIT = 60_000
DOC_TIMEOUT_S = 420


@dataclass(slots=True)
class DocSpec:
    path: str
    brief: str


DOC_SPECS: list[DocSpec] = [
    DocSpec(
        "README.md",
        "Die Einstiegsseite des Projekts. Abschnitte: Titel und Einzeiler; Vision (drei bis fünf Sätze, "
        "was es ist und warum); Problem; Zielgruppe und Nutzungsmoment; Kernfunktionen des MVP (Liste, "
        "je ein Satz); Nicht-Ziele (Liste); Stack und Randbedingungen; Status (frisch aus dem Brainstorm, "
        "noch kein Code) mit Verweis auf CLAUDE.md, docs/SPEC.md und docs/PLAN.md.",
    ),
    DocSpec(
        "docs/SPEC.md",
        "Die fachliche Spezifikation des MVP. Abschnitte: Überblick; Begriffe (kurzes Glossar, nur wenn "
        "nötig); Nutzerflüsse (die zwei bis vier wichtigsten, Schritt für Schritt); Funktionen, je mit "
        "Beschreibung und prüfbaren Akzeptanzkriterien (Gegeben/Wenn/Dann oder Stichpunkte); Datenmodell-"
        "Skizze (Entitäten, Felder, Beziehungen als Text oder Tabelle); Schnittstellen und Integrationen; "
        "Randfälle und Fehlerverhalten; Nicht-funktionale Anforderungen (Performance, Datenschutz, Offline, "
        "Plattform), soweit besprochen; Abgrenzung (Nicht-Ziele).",
    ),
    DocSpec(
        "docs/PLAN.md",
        "Der Umsetzungsplan in Meilensteinen. Meilenstein 1 ist immer ein lauffähiges Grundgerüst, das den "
        "ersten echten Nutzen zeigt (Projekt aufsetzen, Build und Tests laufen, ein Kernpfad Ende zu Ende). "
        "Danach zwei bis vier weitere Meilensteine, jeder in Stunden bis wenigen Tagen machbar. Pro "
        "Meilenstein: Ziel (ein Satz), Aufgaben als Checkliste (konkret, mit Dateien oder Modulen, wo "
        "sinnvoll), Prüfung (wie man sieht, dass er fertig ist), Abhängigkeiten. Am Ende: Reihenfolge-"
        "Begründung und was bewusst nach dem MVP kommt.",
    ),
    DocSpec(
        "docs/DECISIONS.md",
        "Entscheidungsprotokoll im kurzen ADR-Stil. Pro Entscheidung aus dem Gespräch: Nummer und Titel, "
        "Kontext (ein bis zwei Sätze), Entscheidung, Begründung, verworfene Alternativen (falls besprochen), "
        "Datum. Nur echte Entscheidungen des Entwicklers oder ausdrücklich ihm überlassene Punkte, die der "
        "Partner vorgeschlagen und er bestätigt hat. Abschließend ein Hinweis, dass Claude Code neue "
        "Entscheidungen hier ergänzt.",
    ),
    DocSpec(
        "docs/OPEN_QUESTIONS.md",
        "Offene Punkte. Pro Punkt: Frage, warum sie offen ist, Vorschlag (mit Standardannahme, falls "
        "niemand antwortet), und die Angabe, ob sie Meilenstein 1 blockiert (ja/nein) mit Verweis auf "
        "docs/PLAN.md. Am Anfang eine kurze Tabelle als Übersicht. Wenn nichts offen ist, sag das in einem "
        "Satz und lass die Struktur als Vorlage stehen.",
    ),
    DocSpec(
        "CLAUDE.md",
        "Die Arbeitsanweisung für Claude Code in diesem Ordner, knapp und konkret. Abschnitte: Zweck des "
        "Projekts (zwei Sätze); Stack und Werkzeuge (Sprache, Framework, Paketmanager, Test-Runner, Build- "
        "und Prüfbefehle, sobald der Stack feststeht; sonst der Vorschlag, klar gekennzeichnet); "
        "Projektstruktur, die angelegt werden soll; Konventionen (Code-Stil, Tests, Commits klein und "
        "beschreibend, Sprache der Doku deutsch mit englischen Bezeichnern); Wo was steht (docs/SPEC.md, "
        "docs/PLAN.md, docs/DECISIONS.md, docs/OPEN_QUESTIONS.md, docs/BRAINSTORM.md); Arbeitsweise "
        "(Meilensteine aus docs/PLAN.md der Reihe nach, nach jedem Schritt prüfen, neue Entscheidungen in "
        "docs/DECISIONS.md eintragen, nur bei blockierenden Punkten aus docs/OPEN_QUESTIONS.md nachfragen); "
        "Tabus (was nicht angefasst, nicht installiert, nicht nach außen geschickt werden darf, soweit "
        "besprochen; Secrets nie in den Code).",
    ),
]

KICKOFF_TEMPLATE = (
    "Du arbeitest im neuen Projekt {name} in {path}. Lies zuerst CLAUDE.md, docs/SPEC.md und "
    "docs/PLAN.md. Setze Meilenstein 1 aus docs/PLAN.md um: ein lauffähiges Grundgerüst mit dem "
    "ersten echten Nutzen. Halte dich an docs/DECISIONS.md. Bei Punkten aus docs/OPEN_QUESTIONS.md, "
    "die Meilenstein 1 blockieren, frag kurz nach; alles andere entscheidest du sinnvoll und "
    "notierst es in docs/DECISIONS.md. Committe in kleinen Schritten und sag am Ende, was läuft "
    "und wie man es startet."
)

GITIGNORE = "\n".join(
    [
        "# Sidekick Brainstorm: minimaler Start, bei Bedarf erweitern",
        "node_modules/",
        ".venv/",
        "__pycache__/",
        "dist/",
        "build/",
        "target/",
        ".env",
        ".env.*",
        "*.log",
        ".DS_Store",
        "Thumbs.db",
        "",
    ]
)

STEP_LABELS = {
    "folder": "Ordner anlegen",
    "docs": "Dokumente schreiben",
    "local": "Gespräch und Kickoff sichern",
    "git": "Git initialisieren",
    "session": "Session starten",
}


@dataclass(slots=True)
class Job:
    job_id: str
    session_id: str
    status: str = "running"  # running | done | error
    step: int = 0
    total: int = 4 + len(DOC_SPECS)
    label: str = ""
    message: str | None = None
    project_path: str | None = None
    code_session_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MaterializeOptions:
    name: str | None = None
    base_dir: str | None = None
    git_init: bool | None = None
    start_session: bool | None = None


class Materializer:
    def __init__(
        self,
        settings: Callable[[], Settings],
        bus: EventBus,
        db: Database,
        sessions: Any,
        llm: Any,
        prompts_dir: Path | None = None,
        git_runner: Callable[[list[str], Path], tuple[int, str]] | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._db = db
        self._sessions = sessions
        self._llm = llm
        self._git = git_runner or run_git
        self.system_prompt = load_prompt("materialize", prompts_dir)
        self.jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # --- queries -------------------------------------------------------
    def job(self, session_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(session_id)
        return job.to_dict() if job else None

    def base_dir(self, override: str | None = None) -> Path:
        raw = override or self._settings().projects.base_dir or "~/Projects"
        return Path(raw).expanduser()

    def suggest(self, title: str, base_dir: str | None = None) -> dict[str, Any]:
        slug = slugify(title or "")
        path = self.base_dir(base_dir) / slug
        return {"slug": slug, "path": str(path), "exists": path.exists()}

    @staticmethod
    def files(project_path: str | None) -> list[str]:
        if not project_path or not Path(project_path).is_dir():
            return []
        root = Path(project_path)
        rel = [p.relative_to(root) for p in root.rglob("*.md") if ".git" not in p.parts]
        # top-level files first, then docs/, each alphabetically
        return [p.as_posix() for p in sorted(rel, key=lambda p: (len(p.parts), p.as_posix().lower()))]

    @staticmethod
    def kickoff_prompt(name: str, path: str) -> str:
        return KICKOFF_TEMPLATE.format(name=name, path=path)

    # --- lifecycle -----------------------------------------------------
    async def start(self, session_id: str, options: MaterializeOptions | None = None) -> Job:
        current = self.jobs.get(session_id)
        if current is not None and current.status == "running":
            raise RuntimeError("Für diese Session läuft schon ein Anlegen")
        idea = self._sessions.idea(session_id)
        if idea is None:
            row = self._db.get_session(session_id)
            title = (row or {}).get("title") or "Projekt"
            idea = IdeaState(title=title)
        job = Job(job_id=new_id(), session_id=session_id)
        self.jobs[session_id] = job
        task = asyncio.create_task(
            self._run(job, idea, options or MaterializeOptions()), name=f"materialize-{job.job_id}"
        )
        self._tasks[session_id] = task
        return job

    async def wait(self, session_id: str) -> Job | None:
        task = self._tasks.get(session_id)
        if task is not None:
            await task
        return self.jobs.get(session_id)

    async def kickoff(self, session_id: str) -> Any:
        row = self._db.get_session(session_id)
        if row is None:
            raise KeyError(session_id)
        path = row.get("project_path")
        if not path or not Path(path).is_dir():  # noqa: ASYNC240 - a single stat
            raise RuntimeError("Das Projekt wurde noch nicht angelegt")
        name = Path(path).name
        session = await self._sessions.create(path, kind="code", title=name)
        await session.send(self.kickoff_prompt(name, path))
        return session

    # --- the job -------------------------------------------------------
    def _progress(
        self, job: Job, key: str, step: int, message: str | None = None, status: str = "running"
    ) -> None:
        job.step = step
        job.label = STEP_LABELS.get(key, key)
        job.message = message
        job.status = status
        self._bus.publish("materialize_progress", job.to_dict())

    async def _run(self, job: Job, idea: IdeaState, opts: MaterializeOptions) -> None:
        cfg = self._settings()
        git_init = cfg.projects.git_init if opts.git_init is None else opts.git_init
        start_session = (
            cfg.projects.start_session_after_create if opts.start_session is None else opts.start_session
        )
        try:
            # 1. folder
            self._progress(job, "folder", 1)
            base = self.base_dir(opts.base_dir)
            base.mkdir(parents=True, exist_ok=True)
            slug = slugify(opts.name or idea.title or "projekt")
            project = unique_path(base / slug)
            project.mkdir(parents=True)
            (project / "docs").mkdir()
            job.project_path = str(project)
            name = project.name
            if idea.readiness < 60:
                job.warnings.append(
                    f"Bereitschaft nur {idea.readiness} von 100: die Docs bekommen Lücken ({', '.join(idea.gaps()) or 'siehe offene Fragen'})."
                )
            # 2. documents (parallel)
            transcript = self._transcript(job.session_id)
            self._progress(job, "docs", 2, f"0 von {len(DOC_SPECS)}")
            finished = 0

            async def one(spec: DocSpec, index: int) -> None:
                nonlocal finished
                await asyncio.sleep(0.4 * index)  # stagger process starts
                text = await self._generate(spec, name, str(project), idea, transcript, job)
                write_text(project / spec.path, text)
                finished += 1
                self._progress(job, "docs", 2 + finished, f"{spec.path} ({finished} von {len(DOC_SPECS)})")

            await asyncio.gather(*(one(spec, i) for i, spec in enumerate(DOC_SPECS)))
            # 3. local files
            self._progress(job, "local", 2 + len(DOC_SPECS))
            write_text(project / "docs" / "BRAINSTORM.md", self._brainstorm_md(idea, transcript, name))
            write_text(project / "docs" / "KICKOFF.md", self._kickoff_md(name, str(project)))
            write_text(project / ".gitignore", GITIGNORE)
            self._sessions.set_project_path(job.session_id, str(project))
            # 4. git
            self._progress(job, "git", 3 + len(DOC_SPECS))
            if git_init:
                err = await asyncio.to_thread(self._git_init, project)
                if err:
                    job.warnings.append(f"Git: {err}")
                    self._progress(job, "git", 3 + len(DOC_SPECS), f"übersprungen: {err}")
            else:
                self._progress(job, "git", 3 + len(DOC_SPECS), "übersprungen")
            # 5. session
            self._progress(job, "session", 4 + len(DOC_SPECS))
            if start_session:
                try:
                    session = await self._sessions.create(str(project), kind="code", title=name)
                    await session.send(self.kickoff_prompt(name, str(project)))
                    job.code_session_id = session.session_id
                except Exception as exc:  # noqa: BLE001
                    log.exception("kickoff session failed")
                    job.warnings.append(f"Session konnte nicht gestartet werden: {exc}")
            job.finished_at = now_iso()
            self._progress(
                job,
                "session",
                job.total,
                "; ".join(job.warnings) if job.warnings else "Projekt angelegt",
                status="done",
            )
            log.info("materialized brainstorm %s into %s", job.session_id, project)
        except Exception as exc:  # noqa: BLE001
            log.exception("materialize failed")
            job.finished_at = now_iso()
            self._progress(job, job.label or "folder", job.step, f"{exc}", status="error")
            self._bus.publish(
                "error", {"module": "brainstorm", "message": f"Projekt anlegen fehlgeschlagen: {exc}"}
            )

    # --- pieces --------------------------------------------------------
    def _transcript(self, session_id: str) -> str:
        lines: list[str] = []
        for m in self._db.list_messages(session_id, 2000):
            if m["role"] not in ("user", "assistant"):
                continue
            text = "\n".join(b.get("text", "") for b in m["blocks"] if b.get("type") == "text").strip()
            if not text:
                continue
            who = "Entwickler" if m["role"] == "user" else "Partner"
            lines.append(f"{who}: {text}")
        out = "\n\n".join(lines)
        if len(out) > TRANSCRIPT_LIMIT:
            out = "[… Anfang gekürzt …]\n\n" + out[-TRANSCRIPT_LIMIT:]
        return out

    def _doc_prompt(self, spec: DocSpec, name: str, path: str, idea: IdeaState, transcript: str) -> str:
        gaps = ", ".join(idea.gaps()) or "keine"
        return (
            f"Projekt: {name} (Ordner {path})\n"
            f"Datei, die du jetzt schreibst: {spec.path}\n"
            f"Inhalt und Aufbau: {spec.brief}\n"
            f"Lücken laut Ideen-Stand: {gaps}\n"
            f"Bereitschaft laut Partner: {idea.readiness} von 100\n\n"
            "Ideen-Stand (JSON):\n<<<\n"
            f"{json.dumps(idea.to_dict(), ensure_ascii=False, indent=1)}\n>>>\n\n"
            "Gespräch (chronologisch, Sprache-zu-Text, kann Erkennungsfehler enthalten):\n<<<\n"
            f"{transcript or '(kein Gespräch aufgezeichnet)'}\n>>>\n\n"
            f"Gib jetzt nur den Inhalt von {spec.path} aus."
        )

    async def _generate(
        self, spec: DocSpec, name: str, path: str, idea: IdeaState, transcript: str, job: Job
    ) -> str:
        cfg = self._settings()
        prompt = self._doc_prompt(spec, name, path, idea, transcript)
        last_error: str = ""
        for attempt in range(2):
            try:
                text = await self._llm.generate(
                    cfg.brainstorm.docs_model, self.system_prompt, prompt, timeout_s=DOC_TIMEOUT_S
                )
                text = strip_fence(text)
                if text.strip():
                    return text.rstrip() + "\n"
                last_error = "leere Antwort"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                log.warning("doc %s failed (attempt %d): %s", spec.path, attempt + 1, exc)
                await asyncio.sleep(1.0)
        job.warnings.append(f"{spec.path}: Platzhalter ({last_error})")
        return placeholder(spec.path, last_error, idea)

    def _brainstorm_md(self, idea: IdeaState, transcript: str, name: str) -> str:
        date = datetime.now().strftime("%Y-%m-%d %H:%M")
        state = json.dumps(idea.to_dict(), ensure_ascii=False, indent=2)
        return (
            f"# Brainstorm zu {name}\n\n"
            f"Aufgezeichnet von Sidekick am {date}. Das Gespräch ist die Quelle der übrigen Dokumente; "
            "bei Widersprüchen gilt docs/DECISIONS.md.\n\n"
            "## Ideen-Stand zum Schluss\n\n"
            f"```json\n{state}\n```\n\n"
            "## Gespräch\n\n"
            f"{transcript or '(leer)'}\n"
        )

    def _kickoff_md(self, name: str, path: str) -> str:
        return (
            "# Kickoff\n\n"
            "Dieser Prompt startet die erste Claude-Code-Session im Projekt. Sidekick sendet ihn "
            "automatisch, wenn die Session aus dem Brainstorm heraus gestartet wird; er lässt sich auch "
            "von Hand einfügen.\n\n"
            f"```\n{self.kickoff_prompt(name, path)}\n```\n"
        )

    def _git_init(self, project: Path) -> str | None:
        """Initialise a repository with one commit. Returns an error text or None."""
        if shutil.which("git") is None:
            return "git nicht gefunden"
        code, out = self._git(["init", "-q"], project)
        if code != 0:
            return out.strip() or "git init fehlgeschlagen"
        code, out = self._git(["add", "-A"], project)
        if code != 0:
            return out.strip() or "git add fehlgeschlagen"
        code, out = self._git(["commit", "-q", "-m", "Projektstart aus Sidekick-Brainstorm"], project)
        if code != 0 and "who you are" in out.lower() or "identity" in out.lower():
            code, out = self._git(
                [
                    "-c",
                    "user.name=Sidekick",
                    "-c",
                    "user.email=sidekick@localhost",
                    "commit",
                    "-q",
                    "-m",
                    "Projektstart aus Sidekick-Brainstorm",
                ],
                project,
            )
        if code != 0:
            return out.strip() or "git commit fehlgeschlagen"
        return None


# --- helpers ---------------------------------------------------------------------------


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 100):
        candidate = path.with_name(f"{path.name}-{n}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Kein freier Ordnername für {path.name}")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def strip_fence(text: str) -> str:
    """Models sometimes wrap the whole document in a markdown fence; unwrap it."""
    t = text.strip()
    if t.startswith("```") and t.endswith("```"):
        first_nl = t.find("\n")
        if first_nl > 0:
            t = t[first_nl + 1 : -3]
    return t.strip()


def placeholder(path: str, error: str, idea: IdeaState) -> str:
    state = json.dumps(idea.to_dict(), ensure_ascii=False, indent=2)
    return (
        f"# {Path(path).stem}\n\n"
        f"Dieses Dokument konnte nicht automatisch erzeugt werden ({error}). Grundlage für eine "
        "manuelle Fassung: docs/BRAINSTORM.md und der Ideen-Stand unten.\n\n"
        f"```json\n{state}\n```\n"
    )


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        timeout=60,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
