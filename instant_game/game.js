const GAME_DURATION = 30;
let TARGET_JUICE = 100;
const THEME_PRIMARY = 0x2f7d32;
const THEME_ACCENT = 0x8cd867;
const LEMON_TEXTURE = "lime_1";

class LemonScene extends Phaser.Scene {
  constructor() {
    super({ key: "LemonScene" });
  }

  preload() {
    for (let i = 1; i <= 4; i++) {
      this.load.image(`lime_${i}`, `lime_${i}.png`);
    }
    this.load.image("drop_img", "wa.png");
  }

  create() {
    this.timeLeft = GAME_DURATION;
    this.juice = 0;
    this.isPlaying = false;
    this.squeezeCount = 0;

    const centerX = this.scale.width / 2;

    this.add.rectangle(centerX, 200, 480, 400, 0xfff3d6);

    this.lime = this.add.image(centerX, 260, "lime_1").setDisplaySize(154, 154);
    this.lime.setInteractive({ useHandCursor: true });
    this.limeTween = this.tweens.add({
      targets: this.lime,
      scale: { from: 0.9, to: 1.05 },
      yoyo: true,
      repeat: -1,
      duration: 600,
      ease: "Sine.easeInOut",
    });

    this.titleText = this.add.text(centerX - 20, 40, "ภารกิจบีบมะนาวใส่ก๋วยเตี๋ยว", {
      fontSize: "28px",
      fontStyle: "bold",
      color: "#2f3d1e",
      backgroundColor: "#fff3d4",
      padding: { left: 12, right: 12, top: 10, bottom: 6 },
    }).setOrigin(0.5);

    this.timerText = this.add.text(centerX + 80, 100, "เวลา: 30 s", {
      fontSize: "22px",
      color: "#d84315",
      backgroundColor: "rgba(255,255,255,0.8)",
      padding: { left: 8, right: 8, top: 4, bottom: 4 },
    }).setOrigin(0.5);
    this.squeezeText = this.add.text(centerX - 120, 100, "จำนวนบีบ: 0 ครั้ง", {
      fontSize: "22px",
      color: "#2f3d1e",
      backgroundColor: "rgba(255,255,255,0.8)",
      padding: { left: 8, right: 8, top: 4, bottom: 4 },
    }).setOrigin(0.5);

    this.progressBg = this.add.rectangle(centerX, 560, 320, 22, 0xffffff, 0.25).setStrokeStyle(2, 0x2f3d1e, 0.6);
    this.progressFill = this.add.rectangle(centerX - 160, 560, 0, 18, 0xf2c061, 0.95).setOrigin(0, 0.5);
    this.promptText = this.add.text(centerX, 520, `แตะมะนาวเพื่อบีบให้ครบ ${TARGET_JUICE} ครั้ง`, {
      fontSize: "22px",
      color: "#2f3d1e",
      fontStyle: "italic",
      backgroundColor: "rgba(255, 248, 230, 0.9)",
      padding: { left: 12, right: 12, top: 4, bottom: 4 },
    }).setOrigin(0.5);
    this.resultBanner = this.add.text(centerX, 600, "", {
      fontSize: "24px",
      fontStyle: "bold",
      color: "#d84315",
    }).setOrigin(0.5);

    this.lime.on("pointerdown", (pointer) => this.handleSqueeze(pointer));

    this.time.addEvent({
      delay: 1000,
      callback: this.updateTimer,
      callbackScope: this,
      loop: true,
    });

    this.deformTween = null;
    this.createDropTexture();
  }

  createDropTexture() {}

  startGame() {
    this.isPlaying = true;
  }

  handleSqueeze(pointer) {
    if (!this.isPlaying) {
      this.startGame();
    }

    if (this.timeLeft <= 0 || pointer?.isDown === false) {
      return;
    }

    if (pointer) {
      const circleRadius = this.lime.displayWidth * 0.3;
      const inside = Phaser.Math.Distance.Between(pointer.x, pointer.y, this.lime.x, this.lime.y) <= circleRadius;
      if (!inside) {
        return;
      }
    }

    this.squeezeCount = Math.min(this.squeezeCount + 1, TARGET_JUICE);
    const progress = Phaser.Math.Clamp(this.squeezeCount / TARGET_JUICE, 0, 1);
    this.progressFill.width = 280 * progress;
    this.squeezeText.setText(`บีบ: ${this.squeezeCount} ครั้ง`);
    this.updateResultBanner(false);
    this.spawnDrop(pointer);

    if (this.deformTween) {
      this.deformTween.stop();
      this.lime.setScale(1, 1);
    }
    this.deformTween = this.tweens.add({
      targets: this.lime,
      scaleY: { from: 1, to: 0.8 },
      scaleX: { from: 1, to: 1.05 },
      duration: 120,
      yoyo: true,
      ease: "Cubic.easeOut",
      onComplete: () => this.lime.setData("ready", true),
    });

    if (this.squeezeCount >= TARGET_JUICE) {
      this.updateResultBanner(true);
      this.endGame(true);
    }
  }

  spawnDrop(pointer) {
    const baseX = pointer?.x ?? 240;
    const baseY = pointer?.y ?? 260;
    const dropletCount = Phaser.Math.Between(1, 2);
    for (let i = 0; i < dropletCount; i++) {
      const drop = this.add.image(baseX + Phaser.Math.Between(-55, 55), baseY + Phaser.Math.Between(-30, 30), "drop_img");
      drop.setScale(Phaser.Math.FloatBetween(0.08, 0.12));
      drop.setAngle(Phaser.Math.Between(-25, 25));
      drop.setBlendMode(Phaser.BlendModes.ADD);
      this.tweens.add({
        targets: drop,
        y: baseY + (200 - (this.juice / TARGET_JUICE) * 100) + Phaser.Math.Between(30, 100),
        alpha: 0,
        duration: Phaser.Math.Between(400, 800),
        onComplete: () => drop.destroy(),
        ease: "Quad.easeIn",
      });
    }
  }

  updateTimer() {
    if (!this.isPlaying) {
      return;
    }

    this.timeLeft -= 1;
    this.timerText.setText(`เวลา: ${this.timeLeft}s`);

    if (this.timeLeft <= 0) {
      if (!this.squeezeCount >= TARGET_JUICE) {
        this.updateResultBanner(false, true);
      }
      this.endGame(this.squeezeCount >= TARGET_JUICE);
    }
  }

  updateResultBanner(success, timeout = false) {
    if (!this.resultBanner) {
      return;
    }
    if (success) {
      this.resultBanner.setText("🎉 สำเร็จ! บีบครบ 100% 🎉");
      this.resultBanner.setColor("#2f7d32");
    } else {
      const percent = Math.round((this.squeezeCount / TARGET_JUICE) * 100);
      this.resultBanner.setText(timeout ? "Game Over! แตะเล่นใหม่ได้เลย" : `Progress: ${percent}%`);
      this.resultBanner.setColor("#d84315");
    }
  }

  endGame(success) {
    if (this.gameOver) {
      return;
    }
    this.gameOver = true;
    this.isPlaying = false;
    this.scene.pause();

  window.LemonGame.showResult({
      success,
      count: this.squeezeCount,
      timeLeft: this.timeLeft,
    });
  }
}

window.LemonGame = {
  showResult({ success, count, timeLeft }) {
    const overlay = document.getElementById("result-overlay");
    const title = document.getElementById("overlay-title");
    const description = document.getElementById("overlay-description");
    if (!overlay || !title || !description) return;
    if (success) {
      title.textContent = "ภารกิจสำเร็จ! 😀";
      description.textContent = `คุณบีบครบ ${TARGET_JUICE} ครั้งใน ${30 - timeLeft} วินาที`;
    } else {
      title.textContent = "Game Over!";
      description.textContent = `บีบได้ ${count} ครั้ง ลองใหม่อีกครั้งนะ`;
    }
    overlay.dataset.success = success ? "true" : "false";
    overlay.classList.add("visible");
  },
  async captureCanvas() {
    const canvas = document.querySelector("#game-container canvas");
    if (!canvas) {
      return null;
    }
    const bg = document.createElement("canvas");
    bg.width = canvas.width;
    bg.height = canvas.height;
    const ctx = bg.getContext("2d");
    ctx.fillStyle = "#fff8ea";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(canvas, 0, 0);
    return bg.toDataURL("image/png");
  },
};

function launchGame() {
  const overlay = document.getElementById("result-overlay");
  overlay?.classList.remove("visible");
  const container = document.getElementById("game-container");
  if (container) {
    container.innerHTML = "";
  }
  if (!Phaser || !container) return;
  new Phaser.Game({
    type: Phaser.AUTO,
    width: 480,
    height: 800,
    backgroundColor: "#fff8ea",
    parent: "game-container",
    scene: LemonScene,
    render: {
      pixelArt: false,
      antialias: true,
      transparent: false,
      clearBeforeRender: true,
      preserveDrawingBuffer: true,
    },
  });
}

window.addEventListener("load", async () => {
  const shareBtn = document.getElementById("share-result-btn");
  const retryBtn = document.getElementById("retry-btn");
  const copyLinkBtn = document.getElementById("copy-link-btn");

  if (shareBtn) {
    shareBtn.addEventListener("click", async () => {
      const overlay = document.getElementById("result-overlay");
      const success = overlay?.dataset.success === "true";
      const dataUrl = await window.LemonGame.captureCanvas();
      if (!dataUrl) {
        alert("ไม่พบหน้าจอเกม");
        return;
      }
      const preview = document.getElementById("capture-preview");
      if (preview) {
        preview.src = dataUrl;
        preview.style.display = "block";
      }
      const link = document.createElement("a");
      link.href = dataUrl;
      link.download = success ? "game-clear.png" : "game-over.png";
      link.click();
      alert("ดาวน์โหลดรูปเรียบร้อย แชร์ด้วยตัวเองได้ทันที!");
    });
  }

  if (retryBtn) {
    retryBtn.addEventListener("click", launchGame);
  }

  if (copyLinkBtn) {
    copyLinkBtn.addEventListener("click", async () => {
      const url = window.location.href;
      try {
        await navigator.clipboard.writeText(url);
        alert("คัดลอกลิงก์เกมเรียบร้อย ส่งให้เพื่อนได้เลย!");
      } catch (error) {
        console.error(error);
        prompt("คัดลอกลิงก์เกมด้วยตนเอง:", url);
      }
    });
  }

  try {
    const configResp = await fetch("/api/game/config");
    if (configResp.ok) {
      const data = await configResp.json();
      if (data && data.target_squeezes) {
        TARGET_JUICE = parseInt(data.target_squeezes, 10) || TARGET_JUICE;
      }
    }
  } catch (error) {
    console.warn("ใช้ค่าเริ่มต้น TARGET_JUICE", error);
  }

  launchGame();
});
