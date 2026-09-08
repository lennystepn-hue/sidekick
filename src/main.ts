import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/instrument-sans";
import "./style.css";
import { initTheme } from "./composables/theme";

initTheme();

createApp(App).use(createPinia()).mount("#app");
