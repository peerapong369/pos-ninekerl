const pageConfig = window.BILLING_PAGE || {};
const tableCode = pageConfig.tableCode || "";
const promptpayReady = Boolean(pageConfig.promptpayReady);

const rows = Array.from(document.querySelectorAll(".billing-row"));
const summaryBox = document.getElementById("billingSummary");
const hiddenInput = document.getElementById("selectedOrderIds");
const generateBtn = document.getElementById("generateQrBtn");
const confirmBtn = document.getElementById("confirmPaidBtn");
const clearBtn = document.getElementById("clearSelectionBtn");
const qrPreview = document.getElementById("qrPreview");
const qrImage = document.getElementById("qrImage");
const qrAmount = document.getElementById("qrAmount");
const downloadBtn = document.getElementById("downloadQrBtn");
const settleForm = document.getElementById("settleForm");

function getSelection() {
  const selections = [];
  let total = 0;

  rows.forEach((row) => {
    const checkbox = row.querySelector(".order-select");
    if (!checkbox || !checkbox.checked) {
      return;
    }
    const orderId = Number(row.dataset.orderId);
    const balance = Number(row.dataset.balance);
    selections.push({ orderId, balance });
    if (Number.isFinite(balance)) {
      total += balance;
    }
  });

  return {
    ids: selections.map((item) => item.orderId),
    total: Math.round(total * 100) / 100,
    count: selections.length,
  };
}

function updateSummary() {
  const selection = getSelection();
  if (summaryBox) {
    if (!selection.count) {
      summaryBox.innerHTML = "<p>ยังไม่ได้เลือกรายการ</p>";
    } else {
      summaryBox.innerHTML = `<p>เลือกรวม ${selection.count} รายการ • ยอดรวมค้างชำระ <strong>${selection.total.toFixed(
        2
      )} ฿</strong></p>`;
    }
  }

  if (hiddenInput) {
    hiddenInput.value = selection.ids.join(",");
  }
  if (confirmBtn) {
    confirmBtn.disabled = selection.count === 0;
  }
  if (generateBtn) {
    generateBtn.disabled = !promptpayReady || selection.count === 0;
  }

  if (qrPreview) {
    qrPreview.hidden = true;
    if (qrImage) {
      qrImage.removeAttribute("src");
    }
  }
}

async function generateQr() {
  const selection = getSelection();
  if (!selection.count) {
    alert("กรุณาเลือกรายการอย่างน้อย 1 รายการ");
    return;
  }
  if (selection.total <= 0) {
    alert("รายการที่เลือกไม่มียอดค้างชำระ");
    return;
  }

  try {
    if (generateBtn) {
      generateBtn.disabled = true;
      generateBtn.textContent = "กำลังสร้าง QR...";
    }

    const response = await fetch("/admin/billing/qr", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        table_code: tableCode,
        order_ids: selection.ids,
      }),
    });

    if (!response.ok) {
      let message = "ไม่สามารถสร้าง QR ได้";
      try {
        const data = await response.json();
        if (data && typeof data.message === "string" && data.message.trim()) {
          message = data.message.trim();
        }
      } catch (error) {
        const text = await response.text();
        if (text) {
          message = text;
        }
      }
      throw new Error(message);
    }

    const data = await response.json();
    if (!data || !data.qr_image) {
      throw new Error("ข้อมูล QR ไม่ถูกต้อง");
    }

    if (qrImage) {
      qrImage.src = data.qr_image;
    }
    if (qrAmount) {
      const formatted = data.formatted_amount || (data.amount ? Number(data.amount).toFixed(2) : "");
      qrAmount.textContent = formatted;
    }
    if (qrPreview) {
      qrPreview.hidden = false;
    }

    if (downloadBtn) {
      downloadBtn.onclick = () => {
        const link = document.createElement("a");
        link.href = data.qr_image;
        const filename = `promptpay_${tableCode}_${Date.now()}.png`;
        link.setAttribute("download", filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      };
    }
  } catch (error) {
    console.error(error);
    alert(error.message || "ไม่สามารถสร้าง QR ได้");
  } finally {
    if (generateBtn) {
      generateBtn.textContent = "สร้าง QR PromptPay";
      generateBtn.disabled = !promptpayReady || getSelection().count === 0;
    }
  }
}

function clearSelection() {
  rows.forEach((row) => {
    const checkbox = row.querySelector(".order-select");
    if (checkbox) {
      checkbox.checked = false;
    }
  });
  updateSummary();
}

function handleSubmit(event) {
  if (hiddenInput && !hiddenInput.value) {
    event.preventDefault();
    alert("กรุณาเลือกรายการที่ต้องการปิดบิล");
  }
}

rows.forEach((row) => {
  const checkbox = row.querySelector(".order-select");
  if (!checkbox) {
    return;
  }
  checkbox.addEventListener("change", updateSummary);
});

if (generateBtn) {
  generateBtn.addEventListener("click", generateQr);
}
if (clearBtn) {
  clearBtn.addEventListener("click", clearSelection);
}
if (settleForm) {
  settleForm.addEventListener("submit", handleSubmit);
}

updateSummary();
