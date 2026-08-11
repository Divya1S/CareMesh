import { beforeEach, describe, expect, it } from "vitest";
import { clearTokens, getAccessToken, getRefreshToken, isLoggedIn, storeTokens } from "./auth";

describe("token storage", () => {
  beforeEach(() => window.localStorage.clear());

  it("stores and reads a token pair", () => {
    storeTokens("access-1", "refresh-1");
    expect(getAccessToken()).toBe("access-1");
    expect(getRefreshToken()).toBe("refresh-1");
    expect(isLoggedIn()).toBe(true);
  });

  it("clears both tokens", () => {
    storeTokens("access-1", "refresh-1");
    clearTokens();
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
    expect(isLoggedIn()).toBe(false);
  });
});
