const ordersContainer = document.getElementById("kitchenOrders");
const initialOrders = Array.isArray(window.KITCHEN_INITIAL_ORDERS)
  ? window.KITCHEN_INITIAL_ORDERS
  : [];

let currentOrderIds = new Set(initialOrders.map((order) => order.id));
let audioContext = null;

async function fetchOrders() {
  try {
    const response = await fetch("/api/orders/pending");
    if (!response.ok) {
      throw new Error("โหลดออเดอร์ไม่สำเร็จ");
    }
    const orders = await response.json();
    renderOrders(Array.isArray(orders) ? orders : []);
  } catch (error) {
    console.error(error);
  }
}

function renderOrders(orders) {
  if (!orders.length) {
    ordersContainer.innerHTML = "<p>ยังไม่มีออเดอร์</p>";
    currentOrderIds = new Set();
    return;
  }

  const previousIds = currentOrderIds;
  const nextIds = new Set();
  const newOrderIds = [];

  ordersContainer.innerHTML = "";

  orders.forEach((order) => {
    nextIds.add(order.id);
    const isNew = !previousIds.has(order.id);
    if (isNew) {
      newOrderIds.push(order.id);
    }
    const card = buildOrderCard(order, isNew);
    ordersContainer.appendChild(card);
  });

  currentOrderIds = nextIds;
  bindStatusHandlers();

  if (newOrderIds.length) {
    playNotification(newOrderIds.length);
  }
}

function buildOrderCard(order, highlight) {
  const article = document.createElement("article");
  article.className = "order-card";
  article.dataset.orderId = order.id;

  const createdAt = typeof order.created_at === "string" ? order.created_at.replace("T", " ") : "";
  const total = toAmount(order.grand_total ?? order.total);
  const amountPaid = toAmount(order.amount_paid);
  const balanceDue = toAmount(order.balance_due);
  const statusLabel = order.status_label || order.status;
  const statusHint = order.status_hint || "";
  const noteHtml = order.note ? `<p class="order-note">หมายเหตุจากลูกค้า: ${order.note}</p>` : "";
  const itemsHtml = Array.isArray(order.items)
    ? order.items
        .map(
          (item) =>
            `<li><span>${item.quantity} x ${item.name}</span>${
              item.note ? `<em class="note">หมายเหตุ: ${item.note}</em>` : ""
            }</li>`
        )
        .join("")
    : "";

  article.innerHTML = `
    <header>
      <div>
        <h3>โต๊ะ ${order.table} (${order.table_code})</h3>
        <time datetime="${order.created_at}">รับออเดอร์: ${createdAt}</time>
      </div>
      <span class="status-label status-${order.status}">${statusLabel}</span>
    </header>
    <ul class="order-items">${itemsHtml}</ul>
    ${noteHtml}
    <div class="order-finance">
      <div>
        <strong>ยอดรวม ${total.toFixed(2)} ฿</strong>
        ${amountPaid > 0 ? `<span class="paid-amount">ชำระแล้ว ${amountPaid.toFixed(2)} ฿</span>` : ""}
      </div>
      ${
        balanceDue > 0
          ? `<span class="badge badge-warning">ค้างชำระ ${balanceDue.toFixed(2)} ฿</span>`
          : `<span class="badge badge-success">ชำระครบ</span>`
      }
    </div>
    <footer>
      <div class="order-status">
        <label for="statusSelect${order.id}">สถานะ:</label>
        <select
          id="statusSelect${order.id}"
          data-order-id="${order.id}"
          data-previous="${order.status}"
          ${balanceDue > 0 ? 'data-paid-disabled="true"' : ""}
        >
          <option value="pending" ${order.status === "pending" ? "selected" : ""}>รอทำ</option>
          <option value="in_progress" ${order.status === "in_progress" ? "selected" : ""}>กำลังทำ</option>
          <option value="completed" ${order.status === "completed" ? "selected" : ""}>เสิร์ฟแล้ว</option>
          <option value="paid" ${order.status === "paid" ? "selected" : ""}>เช็คบิลแล้ว</option>
        </select>
      </div>
      <div class="order-actions">
        <span class="status-hint">${statusHint}</span>
        <a
          class="button button-small button-outline"
          href="/admin/orders/${order.id}"
          target="_blank"
          rel="noopener"
        >
          ดูรายละเอียด
        </a>
      </div>
    </footer>
  `;

  if (highlight) {
    article.classList.add("order-card--new");
    setTimeout(() => article.classList.remove("order-card--new"), 4000);
  }

  return article;
}

function bindStatusHandlers() {
  ordersContainer.querySelectorAll("select[data-order-id]").forEach((select) => {
    if (!select.dataset.previous) {
      select.dataset.previous = select.value;
    }

    select.addEventListener("focus", () => {
      select.dataset.previous = select.value;
    });

    select.addEventListener("change", async (event) => {
      const target = event.target;
      const orderId = Number(target.dataset.orderId);
      const status = target.value;
      const previous = target.dataset.previous || status;

      if (status === "paid" && target.dataset.paidDisabled === "true") {
        target.value = previous;
        return;
      }

      try {
        const response = await fetch(`/api/orders/${orderId}/status`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ status }),
        });
        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(errorText || "อัปเดตสถานะไม่สำเร็จ");
        }
        const updated = await response.json();
        const card = target.closest("article");
        const statusLabel = card ? card.querySelector(".status-label") : null;
        if (statusLabel) {
          statusLabel.textContent = updated.status_label || status;
          statusLabel.className = `status-label status-${updated.status}`;
        }
        if (status === "paid") {
          card?.remove();
          currentOrderIds.delete(orderId);
        }
        target.dataset.previous = status;
        fetchOrders();
      } catch (error) {
        console.error(error);
        alert("เกิดข้อผิดพลาด กรุณาลองใหม่");
        target.value = previous;
      }
    });
  });
}

function toAmount(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function playNotification(times = 1) {
  if (typeof window.AudioContext !== "function" && typeof window.webkitAudioContext !== "function") {
    return;
  }

  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const unlock = () => audioContext.resume().catch(() => {});
    document.addEventListener("click", unlock, { once: true });
    document.addEventListener("touchstart", unlock, { once: true });
  }

  if (audioContext.state === "suspended") {
    audioContext.resume().catch(() => {});
  }

  const count = Math.min(Math.max(times, 1), 3);
  for (let i = 0; i < count; i += 1) {
    const startTime = audioContext.currentTime + i * 0.35;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();

    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(880, startTime);

    gain.gain.setValueAtTime(0.0001, startTime);
    gain.gain.exponentialRampToValueAtTime(0.25, startTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, startTime + 0.25);

    oscillator.connect(gain).connect(audioContext.destination);
    oscillator.start(startTime);
    oscillator.stop(startTime + 0.3);
  }
}

fetchOrders();
setInterval(fetchOrders, 5000);
