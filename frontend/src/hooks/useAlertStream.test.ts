import { describe, expect, it } from "vitest";
import {
    computeReconnectDelayMs,
    computeTokenRefreshDelayMs,
    isStreamTokenExpiringSoon,
    parseStreamTokenExpiryMs,
} from "./useAlertStream";

describe("useAlertStream reconnect and token refresh helpers", () => {
    it("doubles reconnect delay per failed attempt and caps at 30 seconds", () => {
        expect(computeReconnectDelayMs(0)).toBe(1_500);
        expect(computeReconnectDelayMs(1)).toBe(3_000);
        expect(computeReconnectDelayMs(2)).toBe(6_000);
        expect(computeReconnectDelayMs(3)).toBe(12_000);
        expect(computeReconnectDelayMs(4)).toBe(24_000);
        expect(computeReconnectDelayMs(5)).toBe(30_000);
        expect(computeReconnectDelayMs(10)).toBe(30_000);
        expect(computeReconnectDelayMs(-1)).toBe(1_500);
    });

    it("parses HMAC stream_token expiry and detects near-expiry tokens", () => {
        const expSec = 1_800_000_000;
        const token = `42.${expSec}.deadbeef`;

        expect(parseStreamTokenExpiryMs(token)).toBe(expSec * 1_000);
        expect(parseStreamTokenExpiryMs("malformed")).toBeNull();
        expect(parseStreamTokenExpiryMs(null)).toBeNull();

        // 10 minutes before expiry -> not expiring soon, refresh scheduled 8 min out (2m buffer)
        const tenMinBefore = expSec * 1_000 - 600_000;
        expect(isStreamTokenExpiringSoon(token, tenMinBefore)).toBe(false);
        expect(computeTokenRefreshDelayMs(token, tenMinBefore)).toBe(480_000);

        // 60 seconds before expiry -> expiring soon, refresh clamps to 1s minimum
        const oneMinBefore = expSec * 1_000 - 60_000;
        expect(isStreamTokenExpiringSoon(token, oneMinBefore)).toBe(true);
        expect(computeTokenRefreshDelayMs(token, oneMinBefore)).toBe(1_000);

        // Already expired -> expiring soon
        expect(isStreamTokenExpiringSoon(token, expSec * 1_000 + 5_000)).toBe(true);
    });
});
