import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { VektrynLogo } from "./VektrynLogo";

describe("VektrynLogo", () => {
    it("renders the orbital scan radar svg with custom sizing", () => {
        const html = renderToStaticMarkup(<VektrynLogo className="h-6 w-6" />);

        expect(html).toContain('aria-hidden="true"');
        expect(html).toContain('class="h-6 w-6"');
        expect(html.match(/<path\b/g)).toHaveLength(4);
        expect(html.match(/<circle\b/g)).toHaveLength(2);
    });
});
