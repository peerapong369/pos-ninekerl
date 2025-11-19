const menuConfigs = window.MENU_CONFIGS || {};
const orderState = new Map();

const orderItemsList = document.getElementById("orderItems");
const orderTotalLabel = document.getElementById("orderTotal");
const orderStatusMessage = document.getElementById("orderStatus");
const submitBtn = document.getElementById("submitOrder");
const noteField = document.getElementById("orderNote");
const activeOrdersSection = document.getElementById("activeOrdersSection");
const activeOrdersList = document.getElementById("activeOrders");
const tableToken = window.tableToken || "";

const modal = document.getElementById("menuCustomizer");
const modalTitle = document.getElementById("customizerTitle");
const modalSubtitle = document.getElementById("customizerSubtitle");
const modalImage = document.getElementById("customizerImage");
const groupsContainer = document.getElementById("optionGroupsContainer");
const quantityDisplay = document.getElementById("customizerQuantity");
const priceDisplay = document.getElementById("customizerPrice");
const decreaseBtn = document.getElementById("customizerDecrease");
const increaseBtn = document.getElementById("customizerIncrease");
const addBtn = document.getElementById("customizerAdd");
const cancelBtn = document.getElementById("customizerCancel");
const closeBtn = document.getElementById("customizerClose");
const modalBackdrop = modal ? modal.querySelector(".menu-modal__backdrop") : null;
const specialSection = document.getElementById("specialSection");
const specialToggle = document.getElementById("specialToggle");
const specialLabel = document.getElementById("specialLabel");

const POLL_INTERVAL_MS = 5000;
let pollHandle = null;
let modalState = null;

function formatCurrency(value) {
  return Number(value || 0).toFixed(2);
}

function buildItemKey(menuItemId, optionKey = "base") {
  return `${menuItemId}::${optionKey}`;
}

function buildOptionKeyFromSelections(selections) {
  if (!selections || selections.size === 0) {
    return "base";
  }
  const parts = [];
  selections.forEach((selection, groupId) => {
    if (selection.type === "single") {
      const optionId = selection.option ? selection.option.id : "none";
      parts.push(`${groupId}:${optionId}`);
    } else if (selection.type === "multiple") {
      const ids = Array.from(selection.options.keys()).sort();
      parts.push(`${groupId}:${ids.length ? ids.join("-") : "none"}`);
    }
  });
  return parts.sort().join("|") || "base";
}

function getMenuConfig(menuItemId) {
  const config = menuConfigs[menuItemId];
  if (!config) {
    return {
      groups: [],
      image: null,
      special: null,
    };
  }
  return {
    image: config.image || null,
    image_alt: config.image_alt || null,
    base_price: Number(config.base_price || 0),
    groups: Array.isArray(config.groups) ? config.groups : [],
    special: config.special || null,
  };
}

function calculateUnitPrice(basePrice, selections) {
  let total = Number(basePrice) || 0;
  selections.forEach((selection) => {
    if (selection.type === "single" && selection.option) {
      total += Number(selection.option.price || 0);
    } else if (selection.type === "multiple") {
      selection.options.forEach((option) => {
        total += Number(option.price || 0);
      });
    }
  });
  return Number(total.toFixed(2));
}

function formatOptionLabel(option) {
  const price = Number(option.price || 0);
  return price > 0 ? `${option.name} (+${formatCurrency(price)} ฿)` : option.name;
}

function buildSelectionNote(selections) {
  if (!selections || selections.size === 0) {
    return null;
  }
  const parts = [];
  selections.forEach((selection) => {
    if (selection.type === "single") {
      if (selection.option) {
        parts.push(`${selection.groupName}: ${formatOptionLabel(selection.option)}`);
      }
    } else if (selection.options.size) {
      const names = Array.from(selection.options.values()).map(formatOptionLabel).join(", ");
      parts.push(`${selection.groupName}: ${names}`);
    }
  });
  return parts.length ? parts.join(" | ") : null;
}

function cloneSelectionState(selections) {
  const clone = new Map();
  selections.forEach((selection, groupId) => {
    if (selection.type === "single") {
      clone.set(groupId, {
        type: "single",
        groupName: selection.groupName,
        option: selection.option
          ? {
              id: selection.option.id,
              name: selection.option.name,
              price: Number(selection.option.price || 0),
            }
          : null,
      });
    } else {
      const map = new Map();
      selection.options.forEach((option, optionId) => {
        map.set(optionId, {
          id: option.id,
          name: option.name,
          price: Number(option.price || 0),
        });
      });
      clone.set(groupId, {
        type: "multiple",
        groupName: selection.groupName,
        options: map,
      });
    }
  });
  return clone;
}

function upsertOrderItem(item) {
  const existing = orderState.get(item.key);
  if (existing) {
    existing.quantity += item.quantity;
  } else {
    orderState.set(item.key, item);
  }
  renderOrder();
}

function addSimpleItem(menuItemId, name, basePrice, note = null) {
  const unitPrice = Number(basePrice) || 0;
  const key = buildItemKey(menuItemId, "base");
  upsertOrderItem({
    key,
    menuItemId,
    name,
    unitPrice,
    quantity: 1,
    note,
    selections: null,
  });
}

function addCustomizedItem(state) {
  const optionKey = buildOptionKeyFromSelections(state.selections);
  const key = buildItemKey(state.menuItemId, optionKey);
  const unitPrice = state.currentUnitPrice ?? calculateUnitPrice(state.basePrice, state.selections);
  const selectionNote = buildSelectionNote(state.selections);
  const specialNote = buildSpecialNote(state);
  const noteParts = [];
  if (selectionNote) {
    noteParts.push(selectionNote);
  }
  if (specialNote) {
    noteParts.push(specialNote);
  }
  const note = noteParts.length ? noteParts.join(" | ") : null;

  upsertOrderItem({
    key,
    menuItemId: state.menuItemId,
    name: state.name,
    unitPrice,
    quantity: state.quantity,
    note,
    selections: cloneSelectionState(state.selections),
  });
}

function renderOrder() {
  orderItemsList.innerHTML = "";
  let total = 0;

  orderState.forEach((item, key) => {
    const subtotal = item.unitPrice * item.quantity;
    total += subtotal;

    const li = document.createElement("li");
    li.dataset.itemKey = key;

    const noteHtml = item.note ? `<div class="cart-item-note">${item.note}</div>` : "";

    li.innerHTML = `
      <div class="item-info">
        <strong>${item.name}</strong>
        ${noteHtml}
        <small>${formatCurrency(item.unitPrice)} ฿ ต่อที่</small>
      </div>
      <div class="item-actions">
        <button class="button-small" data-action="decrease" data-item-key="${key}">-</button>
        <span>${item.quantity}</span>
        <button class="button-small" data-action="increase" data-item-key="${key}">+</button>
      </div>
    `;

    orderItemsList.appendChild(li);
  });

  orderTotalLabel.textContent = `${formatCurrency(total)} ฿`;
  submitBtn.disabled = orderState.size === 0;
}

function updateQuantity(itemKey, delta) {
  const item = orderState.get(itemKey);
  if (!item) {
    return;
  }
  item.quantity += delta;
  if (item.quantity <= 0) {
    orderState.delete(itemKey);
  }
  renderOrder();
}

async function submitOrder() {
  const itemsPayload = Array.from(orderState.values()).map((item) => ({
    menu_item_id: item.menuItemId,
    quantity: item.quantity,
    note: item.note || null,
    unit_price: Number(item.unitPrice.toFixed(2)),
  }));

  try {
    submitBtn.disabled = true;
    orderStatusMessage.textContent = "กำลังส่งออเดอร์...";

    const response = await fetch("/api/orders", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        table_code: tableCode,
        items: itemsPayload,
        note: noteField.value.trim() || null,
        token: tableToken,
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      let message = "ส่งออเดอร์ไม่สำเร็จ";
      try {
        const parsed = JSON.parse(text);
        message = parsed.description || parsed.message || message;
      } catch (error) {
        if (text) {
          message = text;
        }
      }
      throw new Error(message);
    }

    await response.json();

    orderState.clear();
    renderOrder();
    noteField.value = "";
    orderStatusMessage.textContent = "ส่งออเดอร์เรียบร้อยแล้ว ขอบคุณค่ะ!";
    await fetchActiveOrders();
  } catch (error) {
    console.error(error);
    orderStatusMessage.textContent = error.message || "เกิดข้อผิดพลาด กรุณาลองอีกครั้ง";
  } finally {
    submitBtn.disabled = orderState.size === 0;
  }
}

async function fetchActiveOrders() {
  try {
    const response = await fetch(`/api/tables/${tableCode}/orders`);
    if (!response.ok) {
      throw new Error("ไม่สามารถดึงข้อมูลคำสั่งซื้อได้");
    }
    const data = await response.json();
    renderActiveOrders(Array.isArray(data.orders) ? data.orders : []);
  } catch (error) {
    console.error(error);
  }
}

function renderActiveOrders(orders) {
  if (!orders.length) {
    activeOrdersSection.hidden = true;
    stopPolling();
    return;
  }

  activeOrdersSection.hidden = false;
  activeOrdersList.innerHTML = orders.map(buildOrderCard).join("");
  ensurePolling();
}

function buildOrderCard(order) {
  const itemsHtml = Array.isArray(order.items)
    ? order.items
        .map(
          (item) =>
            `<li>${item.quantity} x ${item.name}${
              item.note ? ` <em>(หมายเหตุ: ${item.note})</em>` : ""
            }</li>`
        )
        .join("")
    : "";
  const noteHtml = order.note ? `<p class="note">หมายเหตุทั่วไป: ${order.note}</p>` : "";
  const createdAt = typeof order.created_at === "string" ? order.created_at.replace("T", " ") : "";
  const total = Number(order.grand_total ?? order.total ?? 0).toFixed(2);
  const balanceDue = Number(order.balance_due ?? 0);
  const amountPaid = Number(order.amount_paid ?? 0);
  const paymentBadge =
    balanceDue > 0
      ? `<span class="badge badge-warning">ค้างชำระ ${balanceDue.toFixed(2)} ฿</span>`
      : `<span class="badge badge-success">ชำระครบ</span>`;
  const statusHint = order.status_hint ? `<small>${order.status_hint}</small>` : "";
  const orderUrl = new URL(`/order/${order.id}`, window.location.origin).toString();

  return `
    <article class="tracking-card">
      <header>
        <div>
          <strong>ออเดอร์ #${order.id}</strong><br />
          <span class="status-label status-${order.status}">${order.status_label || order.status}</span>
        </div>
        <a href="${orderUrl}" target="_blank" rel="noopener">ดูรายละเอียด</a>
      </header>
      <ul>
        ${itemsHtml}
      </ul>
      ${noteHtml}
      <footer>
        <span>เวลาสั่ง ${createdAt}</span>
        <span>
          ${total} ฿
          ${amountPaid > 0 ? `<small> (จ่ายแล้ว ${amountPaid.toFixed(2)} ฿)</small>` : ""}
        </span>
      </footer>
      <div class="payment-status">
        ${paymentBadge}
        ${statusHint}
      </div>
    </article>
  `;
}

function ensurePolling() {
  if (pollHandle) {
    return;
  }
  pollHandle = setInterval(fetchActiveOrders, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

function getOptionData(groupId, optionId) {
  if (!modalState || !modalState.groupIndex) {
    return null;
  }
  const group = modalState.groupIndex.get(groupId);
  if (!group) {
    return null;
  }
  return group.options.find((option) => String(option.id) === String(optionId)) || null;
}

function initializeSelections(groups) {
  modalState.selections = new Map();
  (groups || []).forEach((group) => {
    if (group.selection_type === "single") {
      const options = group.options || [];
      const defaultOption = group.is_required && options.length ? options[0] : null;
      modalState.selections.set(group.id, {
        type: "single",
        groupName: group.name,
        option: defaultOption
          ? {
              id: String(defaultOption.id),
              name: defaultOption.name,
              price: Number(defaultOption.price || 0),
            }
          : null,
      });
    } else {
      modalState.selections.set(group.id, {
        type: "multiple",
        groupName: group.name,
        options: new Map(),
      });
    }
  });
}

function renderGroups(groups) {
  groupsContainer.innerHTML = "";
  const hasGroups = Array.isArray(groups) && groups.length > 0;
  if (!hasGroups) {
    if (!modalState || !modalState.specialInfo) {
      groupsContainer.innerHTML = '<p class="muted">ไม่มีตัวเลือกเพิ่มเติมสำหรับเมนูนี้</p>';
    }
    return;
  }

  groups.forEach((group) => {
    const selection = modalState.selections.get(group.id);
    const section = document.createElement("section");
    section.className = "modal-section option-group";
    section.dataset.groupId = group.id;

    const header = document.createElement("div");
    header.innerHTML = `<h4>${group.name}</h4>`;
    section.appendChild(header);

    const hint = document.createElement("p");
    hint.className = "muted";
    if (group.selection_type === "single") {
      hint.textContent = group.is_required ? "เลือกได้ 1 รายการ (จำเป็นต้องเลือก)" : "เลือกได้ไม่เกิน 1 รายการ";
    } else {
      hint.textContent = group.is_required ? "เลือกได้หลายรายการ (ต้องเลือกอย่างน้อย 1 รายการ)" : "เลือกได้หลายรายการตามต้องการ";
    }
    section.appendChild(hint);

    const optionGrid = document.createElement("div");
    optionGrid.className = "option-grid";

    if (group.selection_type === "single" && !group.is_required) {
      const label = document.createElement("label");
      label.className = "option-card option-card--none";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `group-${group.id}`;
      input.value = "";
      input.dataset.groupId = group.id;
      input.dataset.optionId = "";
      if (!selection.option) {
        input.checked = true;
        label.classList.add("active");
      }
      const span = document.createElement("span");
      span.textContent = "ไม่เลือก";
      label.appendChild(input);
      label.appendChild(span);
      optionGrid.appendChild(label);
    }

    (group.options || []).forEach((option) => {
      const label = document.createElement("label");
      label.className = "option-card";

      const input = document.createElement("input");
      input.type = group.selection_type === "single" ? "radio" : "checkbox";
      input.name = `group-${group.id}`;
      input.value = option.id;
      input.dataset.groupId = group.id;
      input.dataset.optionId = option.id;
      input.dataset.optionName = option.name;
      input.dataset.optionPrice = option.price || 0;

      const price = Number(option.price || 0);
      const span = document.createElement("span");
      span.textContent = price > 0 ? `${option.name} (+${formatCurrency(price)} ฿)` : option.name;

      if (group.selection_type === "single") {
        const isSelected = selection.option && String(selection.option.id) === String(option.id);
        if (isSelected) {
          input.checked = true;
          label.classList.add("active");
        } else if (!selection.option && group.is_required && option === (group.options || [])[0]) {
          // ensure default required selection is visually marked
          input.checked = true;
          label.classList.add("active");
          selection.option = {
            id: String(option.id),
            name: option.name,
            price: price,
          };
        }
      } else {
        const isChecked = selection.options.has(String(option.id));
        if (isChecked) {
          input.checked = true;
          label.classList.add("active");
        }
      }

      label.appendChild(input);
      label.appendChild(span);
      optionGrid.appendChild(label);
    });

    section.appendChild(optionGrid);
    groupsContainer.appendChild(section);
  });
}

function updateModalSummary() {
  if (!modalState) {
    return;
  }
  let unitPrice = calculateUnitPrice(modalState.basePrice, modalState.selections);
  if (modalState.specialInfo && modalState.specialSelected) {
    unitPrice += Number(modalState.specialInfo.price || 0);
  }
  modalState.currentUnitPrice = Number(unitPrice.toFixed(2));
  priceDisplay.textContent = `${formatCurrency(unitPrice)} ฿`;
  quantityDisplay.textContent = String(modalState.quantity);
}

function adjustModalQuantity(delta) {
  if (!modalState) {
    return;
  }
  modalState.quantity = Math.max(1, modalState.quantity + delta);
  updateModalSummary();
}

function openCustomization(menuItemId, name, basePrice, config, description, imageSrc) {
  const normalizedConfig = config || getMenuConfig(menuItemId);
  const hasSpecial = normalizedConfig.special;
  const hasGroups = Array.isArray(normalizedConfig.groups) && normalizedConfig.groups.length > 0;
  if (!hasSpecial && !hasGroups) {
    addSimpleItem(menuItemId, name, basePrice, description || null);
    return;
  }

  modalState = {
    menuItemId,
    name,
    basePrice: Number(basePrice) || 0,
    description: description || "",
    image: normalizedConfig.image || imageSrc || null,
    quantity: 1,
    groups: normalizedConfig.groups,
    groupIndex: new Map((normalizedConfig.groups || []).map((group) => [group.id, group])),
    selections: new Map(),
    currentUnitPrice: Number(basePrice) || 0,
    specialInfo: normalizedConfig.special
      ? {
          label: normalizedConfig.special.label || "พิเศษ",
          price: Number(normalizedConfig.special.price_delta || 0),
        }
      : null,
    specialSelected: false,
  };

  initializeSelections(normalizedConfig.groups);

  modalTitle.textContent = name;
  modalSubtitle.textContent = description || "เลือกตัวเลือกตามที่ต้องการ";

  if (modalState.image) {
    modalImage.src = modalState.image;
    modalImage.alt = name;
    modalImage.hidden = false;
  } else {
    modalImage.hidden = true;
  }

  renderGroups(normalizedConfig.groups);
  updateSpecialSection();
  updateModalSummary();

  modal.hidden = false;
  document.body.classList.add("modal-open");
}

function closeCustomization() {
  if (!modal) {
    return;
  }
  modalState = null;
  if (groupsContainer) {
    groupsContainer.innerHTML = "";
  }
  resetSpecialSection();
  modal.hidden = true;
  document.body.classList.remove("modal-open");
}

function updateSpecialSection() {
  if (!specialSection || !specialToggle || !specialLabel || !modalState) {
    return;
  }
  if (modalState.specialInfo) {
    specialSection.hidden = false;
    const price = formatCurrency(modalState.specialInfo.price || 0);
    specialLabel.textContent = `${modalState.specialInfo.label || "พิเศษ"} (+${price} ฿)`;
    specialToggle.checked = modalState.specialSelected;
  } else {
    resetSpecialSection();
  }
}

function resetSpecialSection() {
  if (specialSection) {
    specialSection.hidden = true;
  }
  if (specialLabel) {
    specialLabel.textContent = "เลือกแบบพิเศษ";
  }
  if (specialToggle) {
    specialToggle.checked = false;
  }
}

function validateSelections() {
  if (!modalState) {
    return "ไม่พบข้อมูลตัวเลือก";
  }
  for (const [groupId, selection] of modalState.selections.entries()) {
    const group = modalState.groupIndex.get(groupId);
    if (!group || !group.is_required) {
      continue;
    }
    if (selection.type === "single" && !selection.option) {
      return `กรุณาเลือกตัวเลือกสำหรับ ${group.name}`;
    }
    if (selection.type === "multiple" && selection.options.size === 0) {
      return `กรุณาเลือกอย่างน้อย 1 รายการใน ${group.name}`;
    }
  }
  return null;
}

function buildSpecialNote(state) {
  if (!state || !state.specialInfo || !state.specialSelected) {
    return null;
  }
  const price = formatCurrency(state.specialInfo.price || 0);
  return `${state.specialInfo.label || "พิเศษ"} (+${price} ฿)`;
}

if (groupsContainer) {
  groupsContainer.addEventListener("change", (event) => {
    if (!modalState) {
      return;
    }
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const groupId = Number(input.dataset.groupId);
    if (!modalState.selections.has(groupId)) {
      return;
    }
    const selection = modalState.selections.get(groupId);
    const optionId = input.dataset.optionId;

    if (selection.type === "single") {
      const groupInputs = groupsContainer.querySelectorAll(`input[name="group-${groupId}"]`);
      groupInputs.forEach((element) => {
        const label = element.closest("label.option-card");
        if (label) {
          label.classList.remove("active");
        }
      });

      const label = input.closest("label.option-card");
      if (label) {
        label.classList.add("active");
      }

      if (!optionId) {
        selection.option = null;
      } else {
        const optionData = getOptionData(groupId, optionId);
        if (optionData) {
          selection.option = {
            id: String(optionData.id),
            name: optionData.name,
            price: Number(optionData.price || 0),
          };
        }
      }
    } else {
      const label = input.closest("label.option-card");
      if (input.checked) {
        const optionData = getOptionData(groupId, optionId);
        if (optionData) {
          selection.options.set(String(optionData.id), {
            id: String(optionData.id),
            name: optionData.name,
            price: Number(optionData.price || 0),
          });
        }
        if (label) {
          label.classList.add("active");
        }
      } else {
        selection.options.delete(String(optionId));
        if (label) {
          label.classList.remove("active");
        }
      }
    }

    updateModalSummary();
  });
}

if (decreaseBtn) {
  decreaseBtn.addEventListener("click", () => adjustModalQuantity(-1));
}

if (increaseBtn) {
  increaseBtn.addEventListener("click", () => adjustModalQuantity(1));
}

if (cancelBtn) {
  cancelBtn.addEventListener("click", () => closeCustomization());
}

if (closeBtn) {
  closeBtn.addEventListener("click", () => closeCustomization());
}

if (modalBackdrop) {
  modalBackdrop.addEventListener("click", () => closeCustomization());
}

if (addBtn) {
  addBtn.addEventListener("click", () => {
    if (!modalState) {
      return;
    }
    const validationError = validateSelections();
    if (validationError) {
      alert(validationError);
      return;
    }
    addCustomizedItem(modalState);
    closeCustomization();
  });
}

document.querySelectorAll('[data-action="add"]').forEach((button) => {
  button.addEventListener("click", (event) => {
    const itemElement = event.target.closest(".menu-card");
    if (!itemElement) {
      return;
    }
    const menuItemId = Number(itemElement.dataset.itemId);
    const name = itemElement.dataset.itemName || itemElement.querySelector("h4").textContent.trim();
    const price = Number(itemElement.dataset.itemPrice);
    const description = itemElement.dataset.itemDescription || "";
    const imageSrc = itemElement.dataset.itemImage || null;
    const config = getMenuConfig(menuItemId);
    const hasCustomization = Array.isArray(config.groups) && config.groups.length > 0;
    const hasSpecialOption = Boolean(config.special);

    if (hasCustomization || hasSpecialOption) {
      openCustomization(menuItemId, name, price, config, description, imageSrc);
    } else {
      addSimpleItem(menuItemId, name, price, null);
    }
  });
});

orderItemsList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }
  const key = button.dataset.itemKey;
  if (!key) {
    return;
  }
  updateQuantity(key, button.dataset.action === "increase" ? 1 : -1);
});

submitBtn.addEventListener("click", submitOrder);
window.addEventListener("load", fetchActiveOrders);

if (specialToggle) {
  specialToggle.addEventListener("change", () => {
    if (!modalState || !modalState.specialInfo) {
      specialToggle.checked = false;
      return;
    }
    modalState.specialSelected = specialToggle.checked;
    updateModalSummary();
  });
}
