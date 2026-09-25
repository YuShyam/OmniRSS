/**
 * OmniRSS 後端 API 客戶端模組 (API Client & Auth Interceptor).
 *
 * Encapsulates fetch requests with automatic Bearer token headers,
 * 401 unauthenticated redirect/modal prompts, and RFC 7807 error parsing.
 */

import { store } from "./state.js";

class ApiClient {
  constructor() {
    this.baseUrl = window.location.origin;
  }

  getHeaders(customHeaders = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...customHeaders,
    };

    const token = store.get("token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    return headers;
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const isFormData = options.body instanceof FormData;

    const headers = isFormData
      ? { ...(options.headers || {}) }
      : this.getHeaders(options.headers || {});

    // For FormData, delete Content-Type so browser sets boundary automatically
    if (isFormData) {
      delete headers["Content-Type"];
      const token = store.get("token");
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }

    const config = {
      ...options,
      headers,
    };

    try {
      const response = await fetch(url, config);

      // Handle 401 Unauthorized
      if (response.status === 401) {
        if (!endpoint.includes("/api/auth/login") && !endpoint.includes("/api/auth/setup")) {
          store.set("user", null);
          store.set("token", null);
          window.dispatchEvent(new CustomEvent("omnirss:auth-required"));
        }
      }

      if (!response.ok) {
        let errDetail = `HTTP ${response.status} ${response.statusText}`;
        try {
          const errJson = await response.json();
          const rawDetail = errJson.detail || errJson.title || errJson.message || errDetail;
          if (typeof rawDetail === "object" && rawDetail !== null) {
            if (Array.isArray(rawDetail)) {
              errDetail = rawDetail.map((d) => (d.msg || d.message || JSON.stringify(d))).join("; ");
            } else {
              errDetail = rawDetail.msg || rawDetail.message || rawDetail.detail || JSON.stringify(rawDetail);
            }
          } else {
            errDetail = String(rawDetail);
          }
        } catch (_) {}
        const error = new Error(errDetail);
        error.status = response.status;
        error.detail = errDetail;
        throw error;
      }

      // Check if response is JSON
      const contentType = response.headers.get("content-type");
      if (contentType && contentType.includes("application/json")) {
        return await response.json();
      }

      return await response.text();
    } catch (err) {
      console.warn(`API Error [${endpoint}]:`, err.message);
      throw err;
    }
  }

  // Auth Endpoints
  async setup(username, password) {
    return this.request("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  }

  async login(username, password) {
    return this.request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  }

  async logout() {
    return this.request("/api/auth/logout", { method: "POST" });
  }

  async getMe() {
    return this.request("/api/auth/me");
  }

  async regenerateApiKey() {
    return this.request("/api/auth/regenerate-key", { method: "POST" });
  }

  // Feeds & Categories Endpoints
  async getFeedTree() {
    return this.request("/api/feeds/tree");
  }

  async getCategories() {
    return this.request("/api/categories");
  }

  async getCategoryStats(id) {
    return this.request(`/api/categories/${id}/stats`);
  }

  async createCategory(name, icon = "folder", customRetentionDays = null) {
    return this.request("/api/categories", {
      method: "POST",
      body: JSON.stringify({ name, icon, custom_retention_days: customRetentionDays }),
    });
  }

  async updateCategory(id, data) {
    return this.request(`/api/categories/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async deleteCategory(id) {
    return this.request(`/api/categories/${id}`, { method: "DELETE" });
  }

  async getFeeds() {
    return this.request("/api/feeds");
  }

  async addFeed(feedUrl, categoryId = null, customTitle = null, requiresFlareSolverr = false, autoFullText = false) {
    return this.request("/api/feeds", {
      method: "POST",
      body: JSON.stringify({
        feed_url: feedUrl,
        category_id: categoryId,
        custom_title: customTitle,
        requires_flaresolverr: Boolean(requiresFlareSolverr),
        auto_full_text: Boolean(autoFullText),
      }),
    });
  }

  async refreshFeed(id) {
    return this.request(`/api/feeds/${id}/refresh`, {
      method: "POST",
    });
  }

  async refreshCategory(categoryId) {
    return this.request(`/api/categories/${categoryId}/refresh`, {
      method: "POST",
    });
  }

  async refreshFeeds(feedId = null, categoryId = null) {
    const body = {};
    if (feedId) body.feed_id = feedId;
    if (categoryId) body.category_id = categoryId;
    return this.request("/api/feeds/refresh", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async refreshAllFeeds() {
    return this.request("/api/feeds/refresh", {
      method: "POST",
      body: JSON.stringify({}),
    });
  }

  async getRefreshProgress() {
    return this.request("/api/feeds/refresh/progress");
  }

  async getFeed(id) {
    return this.request(`/api/feeds/${id}`);
  }

  async updateFeed(id, data) {
    return this.request(`/api/feeds/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async deleteFeed(id) {
    return this.request(`/api/feeds/${id}`, { method: "DELETE" });
  }

  async testFeedUrl(feedUrl, authUsername = null, authPassword = null, requiresFlareSolverr = false) {
    return this.request("/api/feeds/test-url", {
      method: "POST",
      body: JSON.stringify({
        feed_url: feedUrl,
        auth_username: authUsername || null,
        auth_password: authPassword || null,
        requires_flaresolverr: Boolean(requiresFlareSolverr),
      }),
    });
  }


  // Articles Endpoints
  async getArticles(params = {}) {
    const query = new URLSearchParams();
    if (params.feed_id) query.append("feed_id", params.feed_id);
    if (params.category_id !== undefined && params.category_id !== null) query.append("category_id", params.category_id);
    if (params.is_unread) query.append("is_unread", "true");
    if (params.is_starred) query.append("is_starred", "true");
    if (params.is_trash) query.append("is_trash", "true");
    if (params.tag) query.append("tag", params.tag);
    if (params.tag_id) query.append("tag_id", params.tag_id);
    if (params.search) query.append("search", params.search);
    if (params.page) query.append("page", params.page);
    if (params.page_size) query.append("page_size", params.page_size);
    if (params.limit) query.append("limit", params.limit);
    if (params.offset) query.append("offset", params.offset);

    const qs = query.toString();
    const res = await this.request(`/api/articles${qs ? `?${qs}` : ""}`);
    return res;
  }

  async getArticle(id) {
    return this.request(`/api/articles/${id}`);
  }

  async fetchFullContent(id) {
    return this.request(`/api/articles/${id}/fetch-full-content`, {
      method: "POST",
    });
  }

  async updateArticleState(id, patch) {
    return this.request(`/api/articles/${id}/state`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  }

  async deleteArticle(id, permanent = false) {
    return this.request(`/api/articles/${id}${permanent ? "?permanent=true" : ""}`, {
      method: "DELETE",
    });
  }

  async trashArticle(id, isTrash = true) {
    return this.request(`/api/articles/${id}/trash`, {
      method: "POST",
      body: JSON.stringify({ is_trash: isTrash }),
    });
  }

  async emptyTrash() {
    return this.request("/api/articles/trash/empty", {
      method: "POST",
    });
  }

  async markAllRead(feedId = null, categoryId = null, articleIds = null) {
    const body = {};
    if (articleIds && Array.isArray(articleIds)) body.article_ids = articleIds;
    if (feedId) body.feed_id = feedId;
    if (categoryId) body.category_id = categoryId;
    return this.request("/api/articles/mark-all-read", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  // Rules Endpoints
  async getRules() {
    return this.request("/api/rules");
  }

  async createRule(ruleData) {
    return this.request("/api/rules", {
      method: "POST",
      body: JSON.stringify(ruleData),
    });
  }

  async deleteRule(id) {
    return this.request(`/api/rules/${id}`, { method: "DELETE" });
  }

  async testRule(ruleData) {
    return this.request("/api/rules/test", {
      method: "POST",
      body: JSON.stringify(ruleData),
    });
  }

  async applyRule(id) {
    return this.request(`/api/rules/${id}/apply`, {
      method: "POST",
    });
  }

  async applyAllRules() {
    return this.request("/api/rules/apply-all", {
      method: "POST",
    });
  }

  // Plugins Endpoints
  async getPlugins() {
    return this.request("/api/plugins");
  }

  async togglePlugin(id, isEnabled) {
    return this.request(`/api/plugins/${id}/toggle`, {
      method: "POST",
      body: JSON.stringify({ is_enabled: isEnabled }),
    });
  }

  async resetPluginCircuit(id) {
    return this.request(`/api/plugins/${id}/reset-circuit`, {
      method: "POST",
    });
  }

  // Backup & OPML
  async exportOpml() {
    return this.request("/api/opml/export");
  }

  async importOpml(file) {
    const formData = new FormData();
    formData.append("file", file);
    return this.request("/api/opml/import", {
      method: "POST",
      body: formData,
    });
  }

  async exportUserBackup() {
    return this.request("/api/user/backup");
  }

  // User Settings
  async getUserSettings() {
    return this.request("/api/user/settings");
  }

  async updateUserSettings(settings) {
    return this.request("/api/user/settings", {
      method: "PUT",
      body: JSON.stringify({ settings }),
    });
  }

  // Tags & Labels Endpoints (QuiteRSS Alignment)
  async getTags() {
    return this.request("/api/tags");
  }

  async createTag(tagData, colorHex = "#3b82f6") {
    const payload = typeof tagData === "object" ? tagData : { name: tagData, color_hex: colorHex };
    return this.request("/api/tags", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async updateTag(tagId, tagData) {
    return this.request(`/api/tags/${tagId}`, {
      method: "PUT",
      body: JSON.stringify(tagData),
    });
  }

  async deleteTag(tagId) {
    return this.request(`/api/tags/${tagId}`, {
      method: "DELETE",
    });
  }

  async toggleArticleTag(articleId, tagId, action = "toggle") {
    return this.request(`/api/tags/articles/${articleId}/toggle`, {
      method: "POST",
      body: JSON.stringify({ tag_id: tagId, action }),
    });
  }

  async bindArticleTags(articleId, tagIds) {
    return this.request(`/api/tags/articles/${articleId}/bind`, {
      method: "POST",
      body: JSON.stringify({ tag_ids: tagIds }),
    });
  }

  async batchArticleTags(articleIds, tagId, action = "add") {
    return this.request("/api/tags/articles/batch", {
      method: "POST",
      body: JSON.stringify({ article_ids: articleIds, tag_id: tagId, action }),
    });
  }
}


export const api = new ApiClient();
