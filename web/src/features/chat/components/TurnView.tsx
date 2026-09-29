import type { TierDisplay } from "../tier";
import type { Source } from "../types";
import { AnswerBlock, type AnswerState } from "./AnswerBlock";
import { SourceList } from "./SourceList";
import { TierBadge } from "./TierBadge";

type Props = {
  question: string;
  sources: Source[] | null;
  sourcesDisabled: boolean;
  answer: string;
  state: AnswerState;
  errorMessage?: string | undefined;
  placeholder?: string | undefined;
  tier?: TierDisplay | undefined;
  anchorPrefix: string;
};

export function TurnView(props: Props) {
  const showSources =
    props.sources !== null || props.state === "streaming" || props.sourcesDisabled;
  return (
    <article className="flex flex-col gap-3">
      <p className="self-end rounded-lg bg-surface px-3 py-2 text-sm whitespace-pre-wrap">
        <span className="sr-only">You asked: </span>
        {props.question}
      </p>
      {showSources ? (
        <SourceList
          sources={props.sources}
          disabled={props.sourcesDisabled}
          anchorPrefix={props.anchorPrefix}
        />
      ) : null}
      <AnswerBlock
        text={props.answer}
        state={props.state}
        errorMessage={props.errorMessage}
        placeholder={props.placeholder}
        sourceCount={props.sources?.length ?? 0}
        anchorPrefix={props.anchorPrefix}
      />
      {props.tier ? <TierBadge tier={props.tier} className="self-start" /> : null}
    </article>
  );
}
