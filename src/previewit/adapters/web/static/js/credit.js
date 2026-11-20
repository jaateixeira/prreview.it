// Paddle's checkout for credit (ADR 0026). Loaded only on the Pricing and Credit pages; Paddle's
// own script is fetched from Paddle when one of them opens, never on other pages.
(function () {
  var config = document.getElementById("paddle-config");
  if (!config) return;

  function withPaddle(then) {
    function ready() {
      if (!window.__previewitPaddle) {
        if (config.dataset.environment === "sandbox") Paddle.Environment.set("sandbox");
        Paddle.Initialize({ token: config.dataset.token });
        window.__previewitPaddle = true;
      }
      if (then) then();
    }
    if (window.Paddle) return ready();
    var script = document.createElement("script");
    script.src = "https://cdn.paddle.com/paddle/v2/paddle.js";
    script.onload = ready;
    document.head.appendChild(script);
  }

  // A payment link from Paddle (?_ptxn=...) opens its checkout here.
  if (new URLSearchParams(location.search).has("_ptxn")) withPaddle();

  var buy = document.getElementById("credit-buy");
  if (!buy) return;
  buy.addEventListener("click", function (event) {
    var button = event.target.closest("[data-price]");
    if (!button) return;
    event.preventDefault();
    withPaddle(function () {
      var options = {
        items: [{ priceId: button.dataset.price, quantity: 1 }],
        customData: { user_id: buy.dataset.user },
        settings: { successUrl: buy.dataset.success },
      };
      if (buy.dataset.email) options.customer = { email: buy.dataset.email };
      Paddle.Checkout.open(options);
    });
  });
})();
