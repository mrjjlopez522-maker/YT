import { MemoryRepo } from "../../src/lib/server/memory-repo";
import { serviceSuite } from "../shared/service-suite";

serviceSuite("memory", async () => new MemoryRepo());
