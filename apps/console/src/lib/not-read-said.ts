/** Why nothing was read, by the read's reason, in the design's words (extraction-incomplete-replies, option A). */
const NOT_READ_CAUSE: Record<string, string> = {
  cut_off: 'The model’s reply stopped at its length limit',
  empty: 'The model’s reply held no answer',
  filtered: 'The provider’s filter stopped the reply',
};

/** The reason's sentence with how the retries went, from how many times the model was asked (the first ask and its retries). */
export function notReadSaid(reason: string | null | undefined, tries: number | null | undefined): string {
  if (reason === 'declined') return 'The model answered that it would not help with this content, so nothing was read and no retry was made.';
  const cause = NOT_READ_CAUSE[reason ?? ''];
  if (!cause) return 'No reply answered, so no field was saved.';
  const retries = (tries ?? 1) - 1;
  const how = tries == null ? '' : retries === 0 ? ', and no retry was made' : retries === 1 ? ', and the one retry stopped too' : `, and all ${retries} retries stopped too`;
  return `${cause}${how}. No field was saved.`;
}
