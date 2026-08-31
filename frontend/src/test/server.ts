import { setupServer } from "msw/node";
import { handlers } from "./handlers/nodeCatalog";

/** MSW server used at the component layer (RTL integration tests). */
export const server = setupServer(...handlers);
