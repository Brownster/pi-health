import assert from "node:assert/strict";
import test from "node:test";

import {
  APP_PATHS,
  extensionDetailsPath,
  PLUGINS_ROUTE_COMPATIBILITY,
} from "../src/app/route-contract.ts";

test("extension paths are canonical and safe for direct navigation", () => {
  assert.equal(APP_PATHS.settings, "/settings");
  assert.equal(APP_PATHS.extensions, "/settings/extensions");
  assert.equal(
    extensionDetailsPath("provider with/slash"),
    "/settings/extensions/provider%20with%2Fslash",
  );
});

test("plugins stays operational until the final compatibility cutover", () => {
  assert.deepEqual(PLUGINS_ROUTE_COMPATIBILITY, {
    legacyPath: "/plugins",
    redirectTarget: "/settings/extensions",
    redirectEnabled: false,
  });
});
