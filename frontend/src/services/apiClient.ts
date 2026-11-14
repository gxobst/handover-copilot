/**
 * Centralized typed HTTP client wrapper with RFC 9457 error normalization.
 */

import {
  ApiError,
  getDefaultDetailForStatus,
  getStatusPhrase,
  type ProblemDetails,
} from './errors.ts';

export interface RequestConfig extends Omit<RequestInit, 'body'> {
  /**
   * Key-value query parameters to append to the URL.
   * Automatically serialized and URI-encoded.
   */
  params?: Record<string, string | number | boolean | null | undefined>;
  /**
   * Optional Bearer authentication token.
   * When provided, sets `Authorization: Bearer <token>`.
   */
  token?: string;
  /**
   * Optional override for the API base URL.
   */
  baseUrl?: string;
}

/**
 * Dynamically resolves the API base URL.
 * Reads `import.meta.env.VITE_API_BASE_URL`, defaulting cleanly to `/api` if unset or empty.
 */
export function getBaseUrl(): string {
  const envUrl = typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env.VITE_API_BASE_URL : undefined;
  if (!envUrl || !envUrl.trim()) {
    return '/api';
  }
  return envUrl.trim();
}

/**
 * Normalizes and builds the target URL by combining baseUrl and endpoint,
 * preventing double slashes and serializing query parameters with proper URI encoding.
 */
export function buildUrl(
  endpoint: string,
  params?: Record<string, string | number | boolean | null | undefined>,
  customBaseUrl?: string
): string {
  const baseUrl = customBaseUrl ?? getBaseUrl();
  let fullUrl: string;

  if (/^https?:\/\//i.test(endpoint)) {
    fullUrl = endpoint;
  } else {
    const cleanBase = baseUrl.replace(/\/+$/, '');
    const cleanEndpoint = endpoint.replace(/^\/+/, '');

    // Deduplicate /api prefix if cleanBase ends with /api and cleanEndpoint starts with api/
    let finalPath = cleanEndpoint;
    if (cleanBase.endsWith('/api') && (finalPath === 'api' || finalPath.startsWith('api/'))) {
      finalPath = finalPath.replace(/^api\/?/, '');
    }

    if (!cleanBase) {
      fullUrl = '/' + finalPath;
    } else if (finalPath) {
      fullUrl = `${cleanBase}/${finalPath}`;
    } else {
      fullUrl = cleanBase;
    }
  }

  // Serialize object query parameters
  if (params && typeof params === 'object') {
    const queryEntries: string[] = [];
    for (const [key, val] of Object.entries(params)) {
      if (val !== undefined && val !== null) {
        queryEntries.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(val))}`);
      }
    }
    if (queryEntries.length > 0) {
      const separator = fullUrl.includes('?') ? '&' : '?';
      fullUrl = `${fullUrl}${separator}${queryEntries.join('&')}`;
    }
  }

  return fullUrl;
}

/**
 * Central request executor supporting typed responses, custom headers,
 * query serialization, bearer token auth, and RFC 9457 error normalization.
 */
export async function request<TResponse, TBody = unknown>(
  endpoint: string,
  options: RequestConfig & { method?: string; body?: TBody } = {}
): Promise<TResponse> {
  const { params, token, baseUrl, method = 'GET', body, headers: customHeaders, ...fetchOptions } = options;

  const fullUrl = buildUrl(endpoint, params, baseUrl);
  const headers = new Headers(customHeaders);

  // Set Bearer authentication token if provided and Authorization header is not set
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  // Handle request body and Content-Type header
  let bodyPayload: BodyInit | undefined = undefined;
  if (body !== undefined && body !== null) {
    if (
      typeof body === 'string' ||
      body instanceof Blob ||
      body instanceof FormData ||
      body instanceof URLSearchParams ||
      body instanceof ArrayBuffer
    ) {
      bodyPayload = body as BodyInit;
    } else {
      if (!headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
      }
      bodyPayload = JSON.stringify(body);
    }
  }

  let response: Response;
  try {
    response = await fetch(fullUrl, {
      ...fetchOptions,
      method,
      headers,
      body: bodyPayload,
      signal: fetchOptions.signal,
    });
  } catch (fetchErr: unknown) {
    const errObj = fetchErr && typeof fetchErr === 'object' ? (fetchErr as Record<string, unknown>) : {};
    const errName = typeof errObj.name === 'string' ? errObj.name : '';
    const errMessage = typeof errObj.message === 'string' ? errObj.message : '';

    // Request cancellations via AbortSignal
    if (
      errName === 'AbortError' ||
      errMessage.toLowerCase().includes('aborted') ||
      Boolean(fetchOptions.signal && fetchOptions.signal.aborted)
    ) {
      throw new ApiError(0, 'Request Aborted', {
        type: 'about:blank',
        title: 'Request Aborted',
        status: 0,
        detail: errMessage || 'The request was aborted.',
      });
    }

    // Network disconnects, CORS rejections, browser offline errors (TypeError: Failed to fetch)
    throw new ApiError(0, 'Network Error', {
      type: 'about:blank',
      title: 'Network Error',
      status: 0,
      detail: 'Unable to connect to the server. Please check your network connection.',
    });
  }

  // Handle error responses (status >= 400)
  if (!response.ok || response.status >= 400) {
    const headerTraceId =
      response.headers.get('x-trace-id') ||
      response.headers.get('X-Trace-ID') ||
      undefined;

    const rawText = await response.text();

    // Empty error response body
    if (!rawText || !rawText.trim()) {
      const fallbackTitle = response.statusText || getStatusPhrase(response.status);
      const fallbackDetail = getDefaultDetailForStatus(response.status);
      throw new ApiError(response.status, response.statusText || fallbackTitle, {
        type: 'about:blank',
        title: fallbackTitle,
        status: response.status,
        detail: fallbackDetail,
        traceId: headerTraceId,
      });
    }

    // Attempt to parse RFC 9457 Problem Details or JSON error body
    let parsedJson: Record<string, unknown> | null = null;
    const contentType = response.headers.get('content-type') || '';
    const isJsonLike =
      contentType.includes('application/json') ||
      contentType.includes('application/problem+json') ||
      rawText.trim().startsWith('{');

    if (isJsonLike) {
      try {
        const parsed = JSON.parse(rawText);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          parsedJson = parsed as Record<string, unknown>;
        }
      } catch {
        parsedJson = null;
      }
    }

    if (parsedJson) {
      // Trace ID extraction order: (1) body.traceId, (2) body.trace_id, (3) fallback to header
      const resolvedTraceId =
        typeof parsedJson.traceId === 'string' && parsedJson.traceId.trim()
          ? parsedJson.traceId.trim()
          : typeof parsedJson.trace_id === 'string' && parsedJson.trace_id.trim()
            ? parsedJson.trace_id.trim()
            : headerTraceId;

      const status = typeof parsedJson.status === 'number' ? parsedJson.status : response.status;
      const title =
        typeof parsedJson.title === 'string' && parsedJson.title.trim()
          ? parsedJson.title.trim()
          : response.statusText || getStatusPhrase(status);
      const type =
        typeof parsedJson.type === 'string' && parsedJson.type.trim()
          ? parsedJson.type.trim()
          : 'about:blank';
      const detail =
        typeof parsedJson.detail === 'string' && parsedJson.detail.trim()
          ? parsedJson.detail.trim()
          : typeof parsedJson.message === 'string' && parsedJson.message.trim()
            ? parsedJson.message.trim()
            : getDefaultDetailForStatus(status);

      const problemDetails: ProblemDetails = {
        ...parsedJson,
        type,
        title,
        status,
        detail,
        ...(resolvedTraceId ? { traceId: resolvedTraceId } : {}),
      };

      throw new ApiError(status, response.statusText || title, problemDetails);
    }

    // Upstream non-JSON / HTML / plain-text error response (e.g. gateway 502/503/504)
    const truncatedDetail = rawText.trim().slice(0, 300);
    const statusPhrase = getStatusPhrase(response.status);
    const title = response.statusText || statusPhrase;

    throw new ApiError(response.status, title, {
      type: 'about:blank',
      title: statusPhrase,
      status: response.status,
      detail: truncatedDetail,
      traceId: headerTraceId,
    });
  }

  // Handle HTTP 204 No Content, 205 Reset Content, or empty body
  if (response.status === 204 || response.status === 205 || response.headers.get('content-length') === '0') {
    return undefined as unknown as TResponse;
  }

  const rawText = await response.text();
  if (!rawText || !rawText.trim()) {
    return undefined as unknown as TResponse;
  }

  try {
    return JSON.parse(rawText) as TResponse;
  } catch {
    return rawText as unknown as TResponse;
  }
}

/**
 * HTTP GET convenience method.
 */
export async function get<TResponse>(endpoint: string, config?: RequestConfig): Promise<TResponse> {
  return request<TResponse>(endpoint, { ...config, method: 'GET' });
}

/**
 * HTTP POST convenience method.
 */
export async function post<TResponse, TBody = unknown>(
  endpoint: string,
  body?: TBody,
  config?: RequestConfig
): Promise<TResponse> {
  return request<TResponse, TBody>(endpoint, { ...config, method: 'POST', body });
}

/**
 * HTTP PUT convenience method.
 */
export async function put<TResponse, TBody = unknown>(
  endpoint: string,
  body?: TBody,
  config?: RequestConfig
): Promise<TResponse> {
  return request<TResponse, TBody>(endpoint, { ...config, method: 'PUT', body });
}

/**
 * HTTP DELETE convenience method.
 */
export async function del<TResponse = void>(endpoint: string, config?: RequestConfig): Promise<TResponse> {
  return request<TResponse>(endpoint, { ...config, method: 'DELETE' });
}

export { del as delete };

export const apiClient = {
  get,
  post,
  put,
  delete: del,
  del,
  request,
  buildUrl,
  getBaseUrl,
};

export default apiClient;
