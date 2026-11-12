/**
 * News & Learning (v1 view `news`, review 028a, the read side): read startup news like an investor, and test whether
 * Project Zero saw it coming. One read for the stories (`GET news`, see ./api); the weekly review, the sources view and
 * the refresh status are their own reads. The section is local state, as before (no query param).
 *
 * Every write and run control stays visible and disabled with its reason (./model/deferred): the outcome decisions,
 * the miss audit and the early signal (028b), "Refresh news" and "Re-measure now" (028c). The old Scout Bridge research
 * button is removed.
 */
import { useState } from "react";

import { Async, PageHeader, Segmented } from "@/components/ui";
import { useNews } from "./api";
import { NewsRefresh } from "./components/NewsRefresh";
import { NewsSources } from "./components/NewsSources";
import { StoryList } from "./components/StoryCard";
import { Themes } from "./components/Themes";
import { WeeklyReview } from "./components/WeeklyReview";
import type { NewsPayload } from "./model/types";
import { EMPTY, footerLine, isStoryTab, NOTICE_EMPTY, storiesFor, TABS, type Tab } from "./model/view";
import styles from "./News.module.css";

export default function NewsPage() {
  const q = useNews();
  return (
    <>
      <PageHeader title="News & Learning" subtitle="What happened in European startups — why it matters, and whether Project Zero saw it coming." />
      <NewsRefresh />
      <Async q={q} label="Reading the news…">
        {(d) => <News d={d} />}
      </Async>
    </>
  );
}

function News({ d }: { d: NewsPayload }) {
  const [tab, setTab] = useState<Tab>("today");
  return (
    <div className={styles.page}>
      <div className={styles.intro}>
        <div className={styles.introCard} data-testid="news-concept">
          <div className={styles.kicker}>VC concept of the day</div>
          <b>{d.concept_of_the_day.title}</b>
          <p>{d.concept_of_the_day.text}</p>
        </div>
        <div className={styles.introCard}>
          <div className={styles.kicker}>One thing to notice earlier next time</div>
          <p>{d.notice_earlier || NOTICE_EMPTY}</p>
        </div>
        <div className={styles.introCard} data-testid="news-vs">
          <div className={styles.kicker}>Project Zero vs the news</div>
          <p>
            <b>{d.counts.CAUGHT_EARLY || 0}</b> caught early · <b>{d.counts.KNOWN_LATE || 0}</b> known late · <b>{d.counts.MISSED || 0}</b> missed ·{" "}
            <b>{d.counts.HISTORICAL || 0}</b> historical
            {d.metrics.median_lead_days !== null && <> · median lead {d.metrics.median_lead_days} days</>}
          </p>
          <p className={styles.faint}>
            {d.counts.noise_hidden || 0} noise and {d.counts.low_hidden_from_top || 0} minor stories kept out of the top. {d.note}
          </p>
        </div>
      </div>
      <Segmented value={tab} onChange={setTab} options={TABS.map((t) => ({ value: t.value, label: t.label }))} label="News sections" />
      {tab === "themes" ? (
        <Themes themes={d.themes} />
      ) : tab === "weekly" ? (
        <WeeklyReview />
      ) : tab === "sources" ? (
        <NewsSources />
      ) : (
        isStoryTab(tab) && <StoryList stories={storiesFor(tab, d)} empty={EMPTY[tab]} pzStart={d.pz_start} />
      )}
      <p className={styles.faint} data-testid="news-footer">
        {footerLine(d)}
      </p>
    </div>
  );
}
