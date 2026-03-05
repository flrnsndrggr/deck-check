import { z } from "zod";

export const CardEntrySchema = z.object({
  qty: z.number().int(),
  name: z.string(),
  section: z.string().default("deck"),
  tags: z.array(z.string()).default([]),
  confidence: z.record(z.number()).default({}),
  explanations: z.record(z.string()).default({}),
});

export const DeckParseResponseSchema = z.object({
  commander: z.string().nullable().optional(),
  companion: z.string().nullable().optional(),
  cards: z.array(CardEntrySchema),
  errors: z.array(z.string()).default([]),
  warnings: z.array(z.string()).default([]),
});

export type CardEntry = z.infer<typeof CardEntrySchema>;
export type DeckParseResponse = z.infer<typeof DeckParseResponseSchema>;

export class ApiClient {
  constructor(private base: string) {}

  async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()) as T;
  }

  async get<T>(path: string): Promise<T> {
    const res = await fetch(`${this.base}${path}`);
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()) as T;
  }
}
