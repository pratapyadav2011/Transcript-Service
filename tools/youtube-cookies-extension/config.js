// Overwritten when the transcript service packages this extension for download,
// so the popup opens already pointed at the right server — and, if that service
// has auth enabled, already holding a signed token. Loading this folder straight
// from the repo leaves both blank; type the URL once and keep auth off.
window.TS_CONFIG = { serviceUrl: "", authToken: "" };
