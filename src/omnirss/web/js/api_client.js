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
          errDetail = errJson.detail || errJson.title || errDetail;
        } catch (_) {}
        const error = new Error(errDetail);
        error.status = response.status;
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
  async getCategories() {
    return this.request("/api/categories");
  }

  async createCategory(name, icon = "folder") {
    return this.request("/api/categories", {
      method: "POST",
      body: JSON.stringify({ name, icon }),
    });
  }

  async deleteCategory(id) {
    return this.request(`/api/categories/${id}`, { method: "DELETE" });
  }

  async getFeeds() {
    return this.request("/api/feeds");
  }

  async addFeed(feedUrl, categoryId = null, customTitle = null) {
    return this.request("/api/feeds", {
      method: "POST",
      body: JSON.stringify({
        feed_url: feedUrl,
        category_id: categoryId,
        custom_title: customTitle,
      }),
    });
  }

  async refreshFeed(id) {
    return this.request(`/api/feeds/${id}/refresh`, { method: "POST" });
  }

  async refreshAllFeeds() {
    return this.request("/api/feeds/refresh-all", { method: "POST" });
  }

  async deleteFeed(id) {
    return this.request(`/api/feeds/${id}`, { method: "DELETE" });
  }

  // Articles Endpoints
  async getArticles(params = {}) {
    const query = new URLSearchParams();
    if (params.feed_id) query.append("feed_id", params.feed_id);
    if (params.category_id) query.append("category_id", params.category_id);
    if (params.is_unread) query.append("is_unread", "true");
    if (params.is_starred) query.append("is_starred", "true");
    if (params.is_trash) query.append("is_trash", "true");
    if (params.tag) query.append("tag", params.tag);
    if (params.search) query.append("search", params.search);
    if (params.limit) query.append("limit", params.limit);
    if (params.offset) query.append("offset", params.offset);

    const qs = query.toString();
    return this.request(`/api/articles${qs ? `?${qs}` : ""}`);
  }

  async getArticle(id) {
    return this.request(`/api/articles/${id}`);
  }

  async updateArticleState(id, patch) {
    return this.request(`/api/articles/${id}/state`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  }

  async markAllRead(feedId = null, categoryId = null) {
    const body = {};
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
}

export const api = new ApiClient();
