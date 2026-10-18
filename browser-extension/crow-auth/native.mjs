import { HOST, nativeFailure } from "./contract.mjs";

export async function nativeRequest(send, message) {
  let response;
  try { response = await send(HOST, message); }
  catch (error) { throw new Error(nativeFailure(error?.message)); }
  if (!response || typeof response !== "object" || response.ok !== true) {
    throw new Error(typeof response?.code === "string" ? response.code : "native_protocol_failed");
  }
  return response;
}

export function checkHandshake(response) {
  if (response.host !== HOST || response.protocol !== 1 || response.version !== "0.1.1") {
    throw new Error("native_version_mismatch");
  }
}
