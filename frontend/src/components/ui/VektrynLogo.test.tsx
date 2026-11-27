import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { VektrynLogo } from "./VektrynLogo";
import { WorkspaceLoader } from "./WorkspaceLoader";

describe("VektrynLogo and WorkspaceLoader", () => {
    it("renders the static orbital scan radar svg with custom sizing", () => {
        const html = renderToStaticMarkup(<VektrynLogo className="h-6 w-6" />);

        expect(html).toContain('aria-hidden="true"');
        expect(html).toContain('class="h-6 w-6"');
        expect(html.match(/<path\b/g)).toHaveLength(4);
        expect(html.match(/<circle\b/g)).toHaveLength(2);
        expect(html).not.toContain("vk-orbit-cw");
    });

    it("enables orbital animation classes and blip ping when animated", () => {
        const html = renderToStaticMarkup(<VektrynLogo animated className="h-12 w-12" />);

        expect(html).toContain("vk-orbit-cw");
        expect(html).toContain("vk-orbit-ccw");
        expect(html).toContain("vk-blip-ping");
        expect(html.match(/<circle\b/g)).toHaveLength(3);
    });

    it("renders WorkspaceLoader with animated logo, brand wordmark, and status label", () => {
        const html = renderToStaticMarkup(
            <WorkspaceLoader overlay label="Initializing radar workspace..." />,
        );

        expect(html).toContain("vektryn");
        expect(html).toContain("Initializing radar workspace...");
        expect(html).toContain("vk-orbit-cw");
        expect(html).toContain("vk-sweep-bar");
        expect(html).toContain("fixed inset-0");
    });
});
