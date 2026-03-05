import fs from "node:fs/promises";
import openapiTS from "openapi-typescript";

const OPENAPI_URL = process.env.OPENAPI_URL || "http://localhost:8000/openapi.json";
const outFile = new URL("../src/openapi-types.ts", import.meta.url);

const schema = await fetch(OPENAPI_URL).then((r) => r.json());
const ts = await openapiTS(schema);
await fs.writeFile(outFile, ts, "utf8");
console.log(`Wrote ${outFile.pathname}`);
