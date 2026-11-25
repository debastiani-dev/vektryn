import { useCallback, useEffect, useRef, useState } from "react";
import { vektrynApi } from "../api/client";
import type { LiveMatchAlert, NotificationItem } from "../types/models";
import { alertToNotification, mergeLiveNotification } from "../utils/notifications";
import { useAlertStream } from "./useAlertStream";

export type NotificationFilter = "all" | "unread";
export const NOTIFICATIONS_REFRESH_EVENT = "vektryn:notifications-refresh";
const NOTIFICATION_POLL_INTERVAL_MS = 60_000;

function buildNotificationQuery(filter: NotificationFilter, page: number): string {
    const params = new URLSearchParams();
    if (filter === "unread") {
        params.set("unread", "true");
    }
    if (page > 1) {
        params.set("page", String(page));
    }
    const qs = params.toString();
    return qs ? `?${qs}` : "";
}

export function useNotifications(streamToken: string | null) {
    const [notifications, setNotifications] = useState<NotificationItem[]>([]);
    const [unreadCount, setUnreadCount] = useState(0);
    const [filter, setFilter] = useState<NotificationFilter>("all");
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const notificationsRef = useRef<NotificationItem[]>([]);

    const syncNotifications = useCallback((next: NotificationItem[]) => {
        notificationsRef.current = next;
        setNotifications(next);
    }, []);

    const fetchPage = useCallback(
        async (targetFilter: NotificationFilter, targetPage: number, append: boolean) => {
            if (append) {
                setLoadingMore(true);
            } else {
                setLoading(true);
            }
            try {
                const res = await vektrynApi.listNotifications(
                    buildNotificationQuery(targetFilter, targetPage),
                );
                if (append) {
                    const seen = new Set(notificationsRef.current.map((item) => item.uuid));
                    const fresh = res.results.filter((item) => !seen.has(item.uuid));
                    syncNotifications([...notificationsRef.current, ...fresh]);
                } else {
                    syncNotifications(res.results);
                }
                setUnreadCount(res.unread_count);
                setHasMore(res.next !== null);
                setPage(targetPage);
                setError(null);
            } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to load notifications");
            } finally {
                setLoading(false);
                setLoadingMore(false);
            }
        },
        [syncNotifications],
    );

    const handleIncomingAlert = useCallback(
        (alert: LiveMatchAlert) => {
            const incoming = alertToNotification(alert);
            const { items, addedUnread } = mergeLiveNotification(
                notificationsRef.current,
                incoming,
            );
            if (!addedUnread) {
                return;
            }
            syncNotifications(items);
            setUnreadCount((count) => count + 1);
        },
        [syncNotifications],
    );

    const handleStreamOpen = useCallback(() => {
        if (!streamToken) return;
        void fetchPage(filter, 1, false);
    }, [fetchPage, filter, streamToken]);

    const { alerts, connected, dismissAlert } = useAlertStream(streamToken, {
        onAlert: handleIncomingAlert,
        onOpen: handleStreamOpen,
    });

    useEffect(() => {
        if (!streamToken) {
            return;
        }
        let cancelled = false;
        async function hydrate() {
            try {
                const res = await vektrynApi.listNotifications(
                    buildNotificationQuery(filter, 1),
                );
                if (!cancelled) {
                    syncNotifications(res.results);
                    setUnreadCount(res.unread_count);
                    setHasMore(res.next !== null);
                    setPage(1);
                    setError(null);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(
                        err instanceof Error ? err.message : "Failed to load notifications",
                    );
                }
            }
        }
        void hydrate();
        const intervalId = window.setInterval(() => {
            if (!document.hidden) {
                void hydrate();
            }
        }, NOTIFICATION_POLL_INTERVAL_MS);
        const handleExternalRefresh = () => {
            void hydrate();
        };
        window.addEventListener(NOTIFICATIONS_REFRESH_EVENT, handleExternalRefresh);
        return () => {
            cancelled = true;
            window.clearInterval(intervalId);
            window.removeEventListener(NOTIFICATIONS_REFRESH_EVENT, handleExternalRefresh);
        };
    }, [filter, streamToken, syncNotifications]);

    const refresh = useCallback(async () => {
        if (!streamToken) return;
        await fetchPage(filter, 1, false);
    }, [fetchPage, filter, streamToken]);

    const loadMore = useCallback(async () => {
        if (!streamToken || loadingMore || !hasMore) return;
        await fetchPage(filter, page + 1, true);
    }, [fetchPage, filter, hasMore, loadingMore, page, streamToken]);

    const markRead = useCallback(
        async (uuid: string) => {
            const res = await vektrynApi.markNotificationRead(uuid);
            setUnreadCount(res.unread_count);
            const next =
                filter === "unread"
                    ? notificationsRef.current.filter((item) => item.uuid !== uuid)
                    : notificationsRef.current.map((item) =>
                          item.uuid === uuid ? res.notification : item,
                      );
            syncNotifications(next);
        },
        [filter, syncNotifications],
    );

    const dismiss = useCallback(
        async (uuid: string) => {
            const res = await vektrynApi.dismissNotification(uuid);
            setUnreadCount(res.unread_count);
            syncNotifications(notificationsRef.current.filter((item) => item.uuid !== uuid));
        },
        [syncNotifications],
    );

    const markAllRead = useCallback(async () => {
        const res = await vektrynApi.markAllNotificationsRead();
        setUnreadCount(res.unread_count);
        const nowIso = new Date().toISOString();
        const next =
            filter === "unread"
                ? []
                : notificationsRef.current.map((item) =>
                      item.is_read ? item : { ...item, is_read: true, read_at: nowIso },
                  );
        syncNotifications(next);
    }, [filter, syncNotifications]);

    const visibleNotifications = streamToken ? notifications : [];
    const visibleUnreadCount = streamToken ? unreadCount : 0;

    return {
        notifications: visibleNotifications,
        unreadCount: visibleUnreadCount,
        filter,
        setFilter,
        hasMore: Boolean(streamToken) && hasMore,
        loading,
        loadingMore,
        error,
        refresh,
        loadMore,
        markRead,
        dismiss,
        markAllRead,
        toasts: alerts,
        dismissToast: dismissAlert,
        sseConnected: connected,
    };
}
