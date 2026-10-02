(() => {
  const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  const text = (node) => (node?.innerText || node?.textContent || "").replace(/\s+/g, " ").trim();
  // Keep the card's visual lines too: LinkedIn frequently moves the location
  // between wrappers while retaining the text rendered to the signed-in user.
  const textLines = (node) => String(node?.innerText || node?.textContent || "")
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const absoluteUrl = (value) => {
    try {
      return new URL(value, window.location.origin).href;
    } catch {
      return value || "";
    }
  };

  const jobId = (url) => {
    const value = String(url || "");
    const match = value.match(/(?:jobPosting:|\/jobs\/view\/(?:[^/?#]*-)?)(\d{6,})/i);
    if (match) return match[1];
    try {
      const parsed = new URL(value, window.location.origin);
      return parsed.searchParams.get("currentJobId") || parsed.searchParams.get("jobId") || "";
    } catch {
      return "";
    }
  };

  const canonicalJobUrl = (value, id) => {
    const resolvedId = id || jobId(value);
    return resolvedId ? `https://www.linkedin.com/jobs/view/${resolvedId}/` : absoluteUrl(value);
  };

  function cardSelectors() {
    return [
      "li.jobs-search-results__list-item",
      "li.scaffold-layout__list-item",
      "div.job-card-container",
      "li.job-card-container",
      "li.job-card-container__list-item",
      "li[data-occludable-job-id]",
      "[data-job-id]",
      "[data-entity-urn*='jobPosting']",
    ];
  }

  function jobAnchor(card) {
    if (card.matches?.("a[href*='/jobs/view/'], a[href*='currentJobId='], a[href*='jobId=']") && jobId(card.href)) {
      return card;
    }
    const links = [...card.querySelectorAll("a[href*='/jobs/view/'], a[href*='currentJobId='], a[href*='jobId=']")];
    return links.find((anchor) => jobId(anchor.href)) || null;
  }

  function cardHasJobIdentity(card) {
    return Boolean(
      card.getAttribute("data-occludable-job-id")
      || card.getAttribute("data-job-id")
      || jobId(card.getAttribute("data-entity-urn") || "")
      || jobId(jobAnchor(card)?.href || ""),
    );
  }

  function uniqueCards(cards) {
    return [...new Set(cards)].filter(cardHasJobIdentity);
  }

  function findCards() {
    for (const selector of cardSelectors()) {
      const cards = uniqueCards([...document.querySelectorAll(selector)]);
      if (cards.length) return { cards, selector };
    }
    // LinkedIn periodically renames card classes. The job link and its stable
    // identifier survive those presentation-only changes, so use their nearest
    // list-like ancestor as a conservative last resort.
    const linkCards = uniqueCards([...document.querySelectorAll("a[href*='/jobs/view/'], a[href*='currentJobId='], a[href*='jobId=']")]
      .map((anchor) => anchor.closest("li, article, [role='listitem'], [data-job-id], [data-occludable-job-id]") || anchor));
    if (linkCards.length) return { cards: linkCards, selector: "job-link-fallback" };
    return { cards: [], selector: "" };
  }

  function isVisible(element) {
    if (!(element instanceof Element)) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && Number(style.opacity || "1") > 0
      && rect.width > 2
      && rect.height > 2;
  }

  function challengeAssessment() {
    const { cards, selector } = findCards();
    const visibleJobCards = cards.filter(isVisible).length;
    const challengeFrames = [...document.querySelectorAll("iframe")]
      .filter((frame) => isVisible(frame) && /li\.protechts\.net|challenge|captcha/i.test(frame.src || ""));
    // innerText excludes display:none nodes, so this only represents text the
    // browser is actually rendering for the user.
    const visiblePageText = text(document.body).slice(0, 12000);
    const challengeText = /security verification|unusual activity|verify you are human|captcha/i.test(visiblePageText);
    const visibleChallengeFrames = challengeFrames.map((frame) => frame.src || "").slice(0, 3);
    const challengeVisible = visibleChallengeFrames.length > 0 || challengeText;
    const reason = challengeVisible
      ? (visibleChallengeFrames.length
        ? "LinkedIn protection challenge is visible"
        : "LinkedIn requested a visible security verification")
      : "";
    return {
      reason,
      cardSelector: selector,
      visibleJobCards,
      visibleChallengeFrames,
      challengeText,
      challengeDetected: challengeVisible,
    };
  }

  function scrollContainer() {
    const candidates = [
      document.querySelector(".jobs-search-results-list"),
      document.querySelector(".scaffold-layout__list-container"),
      document.querySelector(".jobs-search-results-list__scroll-container"),
    ].filter(Boolean);
    return candidates.find((element) => element.scrollHeight > element.clientHeight + 20) || document.scrollingElement;
  }

  const locationPattern = /\b(?:españa|spain|valencia|madrid|barcelona|alicante|sevilla|bilbao|zaragoza|málaga|malaga|murcia|galicia|europa|europe|emea|remoto|remote|h[ií]brido|hybrid)\b/i;
  const cardNoisePattern = /\b(?:hace\s+\d+|ago\s+\d+|solicitud(?:es)?|applicant(?:s)?|evaluando|actively hiring|promoted|fácil solicitud|easy apply|jornada completa|full[- ]time|adel[áa]ntate a solicitar|sé de los primeros|be one of the first)\b/i;

  function selectorValues(card, selectors) {
    return selectors.flatMap((selector) => [...card.querySelectorAll(selector)])
      .flatMap((node) => textLines(node))
      .filter(Boolean);
  }

  function firstUseful(values, predicate = () => true) {
    return values.find((value) => predicate(value)) || "";
  }

  function cardMetadata(card, title) {
    const companyValues = selectorValues(card, [
      ".job-card-container__company-name",
      ".job-card-container__primary-description",
      ".artdeco-entity-lockup__subtitle",
      "[data-test-job-company-name]",
    ]);
    const locationValues = selectorValues(card, [
      ".job-card-container__metadata-item",
      ".job-card-container__metadata-wrapper",
      ".artdeco-entity-lockup__caption",
      "[data-test-job-location]",
    ]);
    const visibleLines = textLines(card);
    const usefulLine = (value) => value !== title && !cardNoisePattern.test(value);
    const company = firstUseful(companyValues, (value) => usefulLine(value) && !locationPattern.test(value))
      || firstUseful(visibleLines, (value) => usefulLine(value) && !locationPattern.test(value));
    const location = firstUseful(locationValues, (value) => locationPattern.test(value))
      || firstUseful(visibleLines, (value) => locationPattern.test(value));
    return {
      company,
      location,
      metadata: {
        companySource: companyValues.includes(company) ? "selector" : (company ? "visible_line" : "missing"),
        locationSource: locationValues.includes(location) ? "selector" : (location ? "visible_line" : "missing"),
      },
    };
  }

  function parseCard(card) {
    const anchor = jobAnchor(card) || card.querySelector("a.job-card-list__title, a.job-card-container__link");
    const cardId = card.getAttribute("data-occludable-job-id")
      || card.getAttribute("data-job-id")
      || jobId(card.getAttribute("data-entity-urn") || "")
      || jobId(anchor?.href || "");
    const url = canonicalJobUrl(anchor?.href || "", cardId);
    const title = text(card.querySelector(".job-card-list__title, .job-card-container__link, [data-test-job-title], [data-view-name='job-card-title']"))
      || text(anchor)
      || (anchor?.getAttribute("aria-label") || "");
    const metadata = cardMetadata(card, title);
    // LinkedIn uses both semantic <time> elements and data-test labels across
    // its job-card variants. Preserve the raw label for the server-side gate.
    const time = card.querySelector("time, [data-test-job-posted-date]");
    const postedAt = text(time)
      || text(card.querySelector(".job-card-container__footer-item, .job-card-list__footer-wrapper"));
    return {
      id: cardId || jobId(url) || url,
      url,
      title,
      company: metadata.company,
      location: metadata.location,
      postedAt,
      publishedAt: time?.getAttribute("datetime") || "",
      metadata: metadata.metadata,
    };
  }

  function mergeJob(existing, candidate) {
    if (!existing) return candidate;
    return {
      ...existing,
      title: existing.title || candidate.title,
      company: existing.company || candidate.company,
      location: existing.location || candidate.location,
      postedAt: existing.postedAt || candidate.postedAt,
      publishedAt: existing.publishedAt || candidate.publishedAt,
      metadata: { ...(existing.metadata || {}), ...(candidate.metadata || {}) },
    };
  }

  function collectJobs(found, limit) {
    const { cards, selector } = findCards();
    // The DOM can contain preloaded results below the visible first page. Read
    // only the top `limit` cards so they cannot influence this run at all.
    for (const card of cards.slice(0, limit)) {
      const job = parseCard(card);
      if (!job.id || !job.url || !job.title) continue;
      found.set(job.id, mergeJob(found.get(job.id), job));
    }
    return { cardCount: cards.length, selector };
  }

  // This deliberately starts from job links, rather than from the production
  // card selectors. It is the independent visual inventory used to detect a
  // parser regression without reusing the extractor under test.
  function findReferenceCards() {
    const anchors = [...document.querySelectorAll("a[href*='/jobs/view/'], a[href*='currentJobId='], a[href*='jobId=']")]
      .filter((anchor) => jobId(anchor.href));
    const cards = uniqueCards(anchors.map((anchor) => (
      anchor.closest("[role='listitem'], article, li, [data-occludable-job-id], [data-job-id]") || anchor
    )));
    return { cards, selector: "job-link-reference-inventory" };
  }

  function parseReferenceCard(card) {
    const anchor = jobAnchor(card);
    const cardId = jobId(anchor?.href || "")
      || card.getAttribute("data-occludable-job-id")
      || card.getAttribute("data-job-id")
      || jobId(card.getAttribute("data-entity-urn") || "");
    const url = canonicalJobUrl(anchor?.href || "", cardId);
    const title = text(anchor) || anchor?.getAttribute("aria-label") || "";
    const lines = textLines(card);
    const company = firstUseful(lines, (line) => line !== title && !cardNoisePattern.test(line) && !locationPattern.test(line));
    const location = firstUseful(lines, (line) => locationPattern.test(line));
    const time = card.querySelector("time, [data-test-job-posted-date]");
    return {
      id: cardId || jobId(url) || url,
      url,
      title,
      company,
      location,
      postedAt: text(time)
        || text(card.querySelector(".job-card-container__footer-item, .job-card-list__footer-wrapper")),
      publishedAt: time?.getAttribute("datetime") || "",
    };
  }

  function collectReferenceJobs(found, limit) {
    const { cards, selector } = findReferenceCards();
    // Keep the independent inventory in exactly the same visible-card scope.
    for (const card of cards.slice(0, limit)) {
      const job = parseReferenceCard(card);
      if (!job.id || !job.url || !job.title) continue;
      found.set(job.id, job);
    }
    return { cardCount: cards.length, selector };
  }

  function parseReportedJobTotal(value) {
    const match = String(value || "").match(
      /([\d][\d.,\s\u00a0\u202f]*)\s*(?:empleos?|ofertas?|puestos?|resultados?|jobs?|positions?|results?)\b/i,
    );
    if (!match) return null;
    const count = Number(match[1].replace(/[^\d]/g, ""));
    return Number.isSafeInteger(count) && count >= 0 ? count : null;
  }

  // LinkedIn sometimes virtualises the list: the scroll height can stabilise
  // while it still advertises cards that were never added to the DOM.  Keep
  // the advertised total as a separate completeness proof.
  function reportedJobTotal() {
    const selectors = [
      "[data-test-search-results-count]",
      ".jobs-search-results-list__subtitle",
      ".jobs-search-results__text",
      ".jobs-search-results-list__subtitle span",
    ];
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const total = parseReportedJobTotal(text(node));
        if (total !== null) return { total, source: selector };
      }
    }
    const titleTotal = parseReportedJobTotal(document.title);
    return titleTotal === null
      ? { total: null, source: "" }
      : { total: titleTotal, source: "document.title" };
  }

  function clickLoadMoreJobs() {
    const selectors = [
      "button.infinite-scroller__show-more-button",
      "button[aria-label*='Ver más']",
      "button[aria-label*='Mostrar más']",
      "button[aria-label*='Show more']",
      "button[aria-label*='Load more']",
    ];
    const direct = selectors
      .flatMap((selector) => [...document.querySelectorAll(selector)])
      .find((button) => !button.disabled && isVisible(button));
    const fallback = [...document.querySelectorAll("button")].find((button) => (
      !button.disabled
      && isVisible(button)
      && /\b(ver|mostrar|show|load)\s+(?:más|more)\b.*\b(empleos|jobs|results|resultados|puestos|positions)\b/i.test(text(button))
    ));
    const button = direct || fallback;
    if (!button) return false;
    button.click();
    return true;
  }

  async function extractFirstPage(maxJobs) {
    // Scope is LinkedIn's first, newest page. A legacy zero means this cap.
    const firstPageLimit = Math.min(25, Math.max(1, Number(maxJobs) || 25));
    const found = new Map();
    const referenceFound = new Map();
    const initialChallenge = challengeAssessment();
    if (initialChallenge.reason) {
      return {
        state: "blocked",
        jobs: [],
        referenceJobs: [],
        diagnostics: {
          pageUrl: window.location.href,
          pageTitle: document.title,
          blockingReason: initialChallenge.reason,
          challenge: initialChallenge,
          failureStage: "initial_challenge_check",
        },
        error: initialChallenge.reason,
      };
    }
    const container = scrollContainer();
    if (container === document.scrollingElement) window.scrollTo({ top: 0, behavior: "auto" });
    else if (container) container.scrollTop = 0;
    await sleep(800);
    const initialHeight = container?.scrollHeight || 0;
    let stableRounds = 0;
    let reachedEnd = false;
    let firstPageTargetReached = false;
    let rounds = 0;
    let selector = "";
    let referenceSelector = "";
    let previousCount = -1;
    let previousHeight = -1;
    const maxRounds = 80;
    let loadMoreClicks = 0;
    const maxLoadMoreClicks = 10;

    // The final stable rounds prove that lazy-loaded cards have finished rendering.
    for (; rounds < maxRounds; rounds += 1) {
      const snapshot = collectJobs(found, firstPageLimit);
      const referenceSnapshot = collectReferenceJobs(referenceFound, firstPageLimit);
      selector = snapshot.selector || selector;
      referenceSelector = referenceSnapshot.selector || referenceSelector;
      const height = container?.scrollHeight || document.scrollingElement?.scrollHeight || 0;
      const viewport = container?.clientHeight || window.innerHeight;
      const position = container?.scrollTop || window.scrollY;
      const atBottom = position + viewport >= height - 4;
      const reported = reportedJobTotal();
      const requiredCards = reported.total === null
        ? firstPageLimit
        : Math.min(firstPageLimit, reported.total);

      // The requested scope is only the newest first page. Stop immediately
      // once it is present instead of loading later LinkedIn results.
      if (found.size >= requiredCards) {
        firstPageTargetReached = true;
        break;
      }

      if (atBottom) {
        reachedEnd = true;
        if (found.size === previousCount && height === previousHeight) stableRounds += 1;
        else stableRounds = 0;
        if (loadMoreClicks < maxLoadMoreClicks && clickLoadMoreJobs()) {
          loadMoreClicks += 1;
          reachedEnd = false;
          stableRounds = 0;
          previousCount = -1;
          previousHeight = -1;
          await sleep(1250);
          continue;
        }
      } else {
        stableRounds = 0;
      }

      previousCount = found.size;
      previousHeight = height;
      const nextPosition = Math.min(height, position + Math.max(500, Math.floor(viewport * 0.85)));
      if (container === document.scrollingElement) window.scrollTo({ top: nextPosition, behavior: "auto" });
      else container.scrollTop = nextPosition;
      await sleep(atBottom ? 1000 : 700);
    }

    const productionCapturedAt = new Date().toISOString();
    const finalSnapshot = collectJobs(found, firstPageLimit);
    const referenceCapturedAt = new Date().toISOString();
    const finalReferenceSnapshot = collectReferenceJobs(referenceFound, firstPageLimit);
    selector = finalSnapshot.selector || selector;
    referenceSelector = finalReferenceSnapshot.selector || referenceSelector;
    const finalHeight = container?.scrollHeight || document.scrollingElement?.scrollHeight || 0;
    const finalChallenge = challengeAssessment();
    const finalBlock = finalChallenge.reason;
    const reported = reportedJobTotal();
    const reportedTotalComplete = reported.total === null || found.size >= reported.total;
    const requiredCards = reported.total === null
      ? firstPageLimit
      : Math.min(firstPageLimit, reported.total);
    const stableEmpty = found.size === 0 && reachedEnd && stableRounds >= 3;
    firstPageTargetReached = firstPageTargetReached || found.size >= requiredCards
      || (found.size === 0 && reported.total === 0)
      || stableEmpty;
    const firstPageTargetComplete = firstPageTargetReached;
    const scrollStabilised = reachedEnd && stableRounds >= 3;
    // An empty, stable list is a valid empty result. It must not be reported as
    // partial merely because there were no cards to collect.
    const complete = (firstPageTargetReached || scrollStabilised)
      && firstPageTargetComplete
      && !finalChallenge.challengeDetected;
    const emptyResult = complete && found.size === 0;
    const emptyReason = found.size === 0 ? "No LinkedIn job cards were found" : "";
    const failureStage = finalBlock
      ? "final_challenge_check"
      : (!firstPageTargetComplete
        ? "first_page_target_not_loaded"
        : (complete ? "" : (emptyReason ? "card_discovery" : "scroll_stability")));
    return {
      state: finalChallenge.challengeDetected ? "blocked" : (emptyResult ? "empty" : (complete ? "complete" : "partial")),
      jobs: [...found.values()].slice(0, firstPageLimit),
      // Independent selectors, identical first-page scope for an honest audit.
      referenceJobs: [...referenceFound.values()].slice(0, firstPageLimit),
      diagnostics: {
        pageUrl: window.location.href,
        pageTitle: document.title,
        cardSelector: selector,
        cardsFound: found.size,
        referenceCardSelector: referenceSelector,
        referenceCardsFound: referenceFound.size,
        initialHeight,
        finalHeight,
        reachedEnd,
        stableRounds,
        scrollStabilised,
        rounds: rounds + 1,
        maxRounds,
        loadMoreClicks,
        maxLoadMoreClicks,
        firstPageLimit,
        firstPageRequiredCards: requiredCards,
        firstPageTargetReached,
        firstPageTargetComplete,
        reportedJobTotal: reported.total,
        reportedJobTotalSource: reported.source,
        reportedTotalComplete,
        blockingReason: finalBlock,
        challenge: finalChallenge,
        challengeDetected: Boolean(finalChallenge.challengeDetected),
        productionCapturedAt,
        referenceCapturedAt,
        capturedAt: referenceCapturedAt,
        failureStage,
      },
      error: complete
        ? ""
        : (finalBlock
          || (!firstPageTargetComplete
            ? `LinkedIn needs ${requiredCards} first-page jobs but only ${found.size} loaded`
            : (emptyReason || "LinkedIn results did not stabilise at the end of the first page"))),
    };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "extractLinkedInFirstPage") return undefined;
    extractFirstPage(message.maxJobs)
      .then(sendResponse)
      .catch((error) => sendResponse({
        state: "failed",
        jobs: [],
        diagnostics: { pageUrl: window.location.href },
        error: error instanceof Error ? error.message : String(error),
      }));
    return true;
  });
})();
