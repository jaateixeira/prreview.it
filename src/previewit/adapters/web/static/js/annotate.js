// Pins a comment to selected text: records the quote and where it starts and ends
// (in characters) so the server can check it against the revision. No dependencies.
document.addEventListener("selectionchange", () => {
  const box = document.querySelector("[data-annotatable]");
  const quote = document.getElementById("comment-quote");
  if (!box || !quote) return;
  const pre = box.querySelector("pre");
  const sel = window.getSelection();
  if (!pre || !sel || sel.rangeCount === 0 || sel.isCollapsed) return;
  const range = sel.getRangeAt(0);
  if (!pre.contains(range.startContainer) || !pre.contains(range.endContainer)) return;
  const before = document.createRange();
  before.selectNodeContents(pre);
  before.setEnd(range.startContainer, range.startOffset);
  const start = Array.from(before.toString()).length;
  const text = range.toString();
  quote.value = text;
  document.getElementById("comment-start").value = start;
  document.getElementById("comment-end").value = start + Array.from(text).length;
  document.getElementById("comment-selected").textContent = "“" + text.slice(0, 200) + "”";
  document.getElementById("comment-submit").disabled = false;
});
