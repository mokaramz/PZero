import { describe, expect, it } from "vitest";

import { conversation, statusOffline, statusReady } from "../test/fixtures";
import {
  CONTEXT_KEYS,
  SUGGESTIONS,
  contextBody,
  headerState,
  inAppLink,
  isOffline,
  isRetiredLink,
  lastAssistantOf,
  offlineReason,
  readContext,
  stateFor,
  toolsUsed,
  when,
} from "./associate";
import type { Msg } from "./types";

const answer = (over: Partial<Msg> = {}): Msg => ({ role: "assistant", at: "2026-11-13T08:00:00Z", text: "ok", ...over });

describe("PZ Associate model", () => {
  it("six suggestion chips, none naming a retired Scout view", () => {
    expect(SUGGESTIONS).toHaveLength(6);
    for (const s of SUGGESTIONS) expect(s).not.toMatch(/scout/i);
    expect(SUGGESTIONS).toContain("What should I focus on today?");
    expect(SUGGESTIONS).toContain("Explain how a company reaches Radar.");
  });

  it("reads ?company= and ?candidate= (in that order); the retired ?item= is ignored", () => {
    expect(CONTEXT_KEYS).toEqual(["company", "candidate"]);
    expect(readContext(new URLSearchParams("company=lumenfold"))).toEqual({ key: "company", value: "lumenfold" });
    expect(readContext(new URLSearchParams("candidate=cand-nimbra&company=lumenfold"))).toEqual({ key: "company", value: "lumenfold" });
    expect(readContext(new URLSearchParams("candidate=cand-nimbra"))).toEqual({ key: "candidate", value: "cand-nimbra" });
    expect(readContext(new URLSearchParams("item=s-0042"))).toBeNull();
    expect(readContext(new URLSearchParams("q=hello&c=c-0a1b2c3d4e5f"))).toBeNull();
    expect(contextBody({ key: "company", value: "lumenfold" })).toEqual({ company: "lumenfold" });
    expect(contextBody(null)).toBeNull();
  });

  it("Ardea's state: uncertain for documentation-only or a dropped reference, else done; thinking while pending", () => {
    expect(stateFor(answer({ mode: "offline" }))).toBe("uncertain");
    expect(stateFor(answer({ mode: "model", notes: ["1 uncited reference(s) removed"] }))).toBe("uncertain");
    expect(stateFor(answer({ mode: "model", notes: ["the selected company 'x' was not found"] }))).toBe("uncertain");
    expect(stateFor(answer({ mode: "model", notes: ["unsupported action(s) removed: Send"] }))).toBe("uncertain");
    expect(stateFor(answer({ mode: "model", notes: ["kept with you: sending a message to the Manager"] }))).toBe("done");
    expect(stateFor(answer({ mode: "model" }))).toBe("done");
    expect(headerState(true, answer())).toBe("thinking");
    expect(headerState(false, undefined)).toBe("ready");
    expect(headerState(false, answer({ mode: "offline" }))).toBe("uncertain");
  });

  it("the offline banner: shown when the kill switch is on or no model is ready, with the reason in words", () => {
    expect(isOffline(undefined)).toBe(false);
    expect(isOffline(statusReady())).toBe(false);
    expect(isOffline(statusOffline())).toBe(true);
    expect(offlineReason(statusOffline())).toBe("paid AI is switched off");
    const noKey = { ...statusOffline(), kill_switch: null };
    expect(isOffline(noKey)).toBe(true);
    expect(offlineReason(noKey)).toBe("no API key is set for the CHEAP role");
    expect(offlineReason({ ...noKey, model: { ready: false, problem: null } })).toBe("no model is configured");
  });

  it("the tool trace in words, and the last answer of a conversation", () => {
    const c = conversation();
    expect(toolsUsed(c.messages[1])).toEqual(["manager decisions", "company detail", "candidate detail"]);
    expect(toolsUsed(c.messages[0])).toEqual([]);
    expect(lastAssistantOf(c.messages)).toBe(c.messages[1]);
    expect(lastAssistantOf([c.messages[0]])).toBeUndefined();
  });

  it("in-app links only: internal, never protocol-relative, never a retired Scout view", () => {
    expect(inAppLink("/conviction?company=lumenfold")).toBe("/conviction?company=lumenfold");
    expect(inAppLink("/")).toBe("/");
    expect(inAppLink("//evil.example")).toBeNull();
    expect(inAppLink("https://lumenfold.example")).toBeNull();
    expect(inAppLink(undefined)).toBeNull();
    for (const l of ["/scout-intake", "/scout-intake?item=s-1", "/scout-intake?tab=native", "/scout-bridge", "/Scout-Bridge/x"]) {
      expect(isRetiredLink(l)).toBe(true);
      expect(inAppLink(l)).toBeNull();
    }
    expect(isRetiredLink("/scout-intakes")).toBe(false);
    expect(isRetiredLink("/deal-flow")).toBe(false);
  });

  it("when: a short local date and time, empty for nothing or garbage", () => {
    expect(when(undefined)).toBe("");
    expect(when("not a date")).toBe("");
    expect(when("2026-11-12T15:20:00Z")).toMatch(/12/);
  });
});
