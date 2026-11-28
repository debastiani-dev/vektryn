import { describe, expect, it } from "vitest";
import { computeReconnectDelayMs } from "./useAlertStream";

describe("useAlertStream reconnect backoff", () => {
    it("doubles delay per failed attempt and caps at 30 seconds", () => {
        expect(computeReconnectDelayMs(0)).toBe(1_500);
        expect(computeReconnectDelayMs(1)).toBe(3_000);
        expect(computeReconnectDelayMs(2)).toBe(6_000);
        expect(computeReconnectDelayMs(3)).toBe(12_000);
        expect(computeReconnectDelayMs(4)).toBe(24_000);
        expect(computeReconnectDelayMs(5)).toBe(30_000);
        expect(computeReconnectDelayMs(10)).toBe(30_000);
        expect(computeReconnectDelayMs(-1)).toBe(1_500);
    });
});
