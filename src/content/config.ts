import { defineCollection, z } from 'astro:content';

const lessons = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    unit: z.string().optional(),
    exercise: z.boolean().default(false),
    parentUnitSlug: z.string().optional(),
  }),
});

export const collections = {
  lessons,
};
