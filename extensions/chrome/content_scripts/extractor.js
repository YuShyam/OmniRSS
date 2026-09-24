/**
 * OmniRSS Chrome Extension 網頁內文與中繼資料擷取器 (Content Extractor Script).
 *
 * Extracts 13 metadata fields, clean article HTML, OG media, and author information from the current tab.
 */

(() => {
  function extractPageArticle() {
    const url = window.location.href;
    const title =
      document.querySelector('meta[property="og:title"]')?.content ||
      document.querySelector('meta[name="twitter:title"]')?.content ||
      document.title ||
      "Untitled Article";

    const author =
      document.querySelector('meta[name="author"]')?.content ||
      document.querySelector('meta[property="article:author"]')?.content ||
      document.querySelector('.author, .byline, [rel="author"]')?.textContent?.trim() ||
      null;

    const coverImageUrl =
      document.querySelector('meta[property="og:image"]')?.content ||
      document.querySelector('meta[name="twitter:image"]')?.content ||
      document.querySelector("article img, main img")?.src ||
      null;

    const snippet =
      document.querySelector('meta[property="og:description"]')?.content ||
      document.querySelector('meta[name="description"]')?.content ||
      document.body.innerText.slice(0, 200).trim();

    // 複製主體內容並移除干擾元素
    let contentClone = null;
    const mainContainer = document.querySelector("article, main, .post-content, .article-content, #content");
    if (mainContainer) {
      contentClone = mainContainer.cloneNode(true);
    } else {
      contentClone = document.body.cloneNode(true);
    }

    // 移除腳本、樣式、導覽列、頁尾與廣告
    const removeSelectors = [
      "script",
      "style",
      "noscript",
      "iframe",
      "nav",
      "header",
      "footer",
      "aside",
      ".ad",
      ".ads",
      ".advertisement",
      ".sidebar",
      ".comments",
    ];
    removeSelectors.forEach((sel) => {
      contentClone.querySelectorAll(sel).forEach((el) => el.remove());
    });

    const htmlContent = contentClone.innerHTML;

    return {
      url,
      title: title.trim(),
      author: author ? author.trim() : null,
      cover_image_url: coverImageUrl,
      snippet: snippet ? snippet.trim() : "",
      html_content: htmlContent,
    };
  }

  // 監聽來自 Popup 或 Background 的擷取訊息
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "EXTRACT_PAGE_DATA") {
      try {
        const data = extractPageArticle();
        sendResponse({ success: true, data });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    }
    return true;
  });
})();
