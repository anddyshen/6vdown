"""订阅更新汇聚确认对话框：
聚焦每部剧最新一集的推送，附带全部分集查看入口及 Emby 历史漏集补全提示。
"""
from __future__ import annotations

from typing import Callable, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..subscription_engine import SubscriptionUpdate


class SubscriptionCard(QFrame):
    """单部剧集的更新展示卡片。"""

    def __init__(
        self,
        update_item: SubscriptionUpdate,
        on_open_detail: Optional[Callable] = None,
        on_change: Optional[Callable] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.update_item = update_item
        self.on_open_detail = on_open_detail
        self.on_change = on_change
        self.sub = update_item.sub
        self.latest = update_item.latest_candidate
        self.missing_history = update_item.missing_history

        # 记录当前卡片选中的下载任务列表（最新集 + 可选的历史漏集）
        self._current_candidate = dict(self.latest) if self.latest else None
        self._include_missing_history = False

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            SubscriptionCard {
                background: palette(base);
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-bottom: 6px;
            }
        """)
        self._build()

    def _build(self) -> None:
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(12, 10, 12, 10)
        main_lay.setSpacing(6)

        # 顶部主行：勾选框 + 剧名 + 最新集徽章 + 画质下拉 + 查看全部详情按钮
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.chk_main = QCheckBox()
        self.chk_main.setChecked(True if self.latest else False)
        self.chk_main.stateChanged.connect(self._on_check_changed)
        top_row.addWidget(self.chk_main)

        title_lbl = QLabel(f"《{self.sub.title}》")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #1e293b;")
        title_lbl.setToolTip(f"{self.sub.title}\n{self.sub.detail_url}")
        top_row.addWidget(title_lbl)

        if self.latest:
            ep_badge = QLabel(f"★ 最新 {self.latest['ep_label']}")
            ep_badge.setStyleSheet("""
                background: #dcfce7;
                color: #15803d;
                font-size: 12px;
                font-weight: 600;
                padding: 2px 8px;
                border-radius: 4px;
            """)
            top_row.addWidget(ep_badge)

            # 画质选择下拉框（若有多个画质备选）
            options = self.latest.get("options") or []
            if len(options) > 1:
                self.combo_q = QComboBox()
                self.combo_q.setStyleSheet("font-size: 12px; font-weight: 500; padding: 2px 6px;")
                for opt in options:
                    self.combo_q.addItem(f"★ {opt['quality']}", opt)
                # 默认选中推荐的最优画质
                for idx, opt in enumerate(options):
                    if opt["quality"] == self.latest["quality"]:
                        self.combo_q.setCurrentIndex(idx)
                        break
                self.combo_q.currentIndexChanged.connect(self._on_quality_changed)
                top_row.addWidget(self.combo_q)
            else:
                q_lbl = QLabel(f"★ {self.latest['quality']}")
                q_lbl.setStyleSheet("""
                    background: #dbeafe;
                    color: #1d4ed8;
                    font-size: 12px;
                    font-weight: 600;
                    padding: 2px 8px;
                    border-radius: 4px;
                """)
                top_row.addWidget(q_lbl)
        else:
            # 最新集已拥有，仅有历史漏集
            no_new_lbl = QLabel("（最新集已下载）")
            no_new_lbl.setStyleSheet("color: #64748b; font-size: 12px;")
            top_row.addWidget(no_new_lbl)

        top_row.addStretch(1)

        # 详情页入口按钮
        self.btn_detail = QPushButton("📋 查看全部分集")
        self.btn_detail.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detail.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                padding: 4px 10px;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                background: palette(button);
            }
            QPushButton:hover {
                border-color: #3b82f6;
                color: #2563eb;
            }
        """)
        self.btn_detail.clicked.connect(self._open_detail)
        top_row.addWidget(self.btn_detail)

        main_lay.addLayout(top_row)

        # 底部提示行（若 Emby 或本地检测到缺失历史剧集）
        if self.missing_history:
            sub_bar = QFrame()
            sub_bar.setStyleSheet("""
                QFrame {
                    background: #fef3c7;
                    border: 1px solid #fde68a;
                    border-radius: 4px;
                    padding: 4px 8px;
                }
            """)
            sb_lay = QHBoxLayout(sub_bar)
            sb_lay.setContentsMargins(6, 4, 6, 4)
            sb_lay.setSpacing(8)

            missing_labels = [m["ep_label"] for m in self.missing_history]
            preview = ", ".join(missing_labels[:3])
            if len(missing_labels) > 3:
                preview += f" 等共 {len(missing_labels)} 集"

            tip_prefix = "💡 媒体库检测到" if self.update_item.has_emby else "💡 历史检测"
            tip_msg = f"{tip_prefix}还缺少 <b>{len(self.missing_history)}</b> 集历史剧集（{preview}）"
            warn_lbl = QLabel(tip_msg)
            warn_lbl.setStyleSheet("color: #92400e; font-size: 12px;")
            sb_lay.addWidget(warn_lbl)
            sb_lay.addStretch(1)

            # 快速补全按钮
            self.btn_toggle_missing = QPushButton("＋ 一并下载缺失集")
            self.btn_toggle_missing.setCheckable(True)
            self.btn_toggle_missing.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_toggle_missing.setStyleSheet("""
                QPushButton {
                    font-size: 11px;
                    padding: 2px 8px;
                    background: #fbbf24;
                    color: #78350f;
                    font-weight: 600;
                    border: none;
                    border-radius: 3px;
                }
                QPushButton:checked {
                    background: #f59e0b;
                    color: #fff;
                }
            """)
            self.btn_toggle_missing.clicked.connect(self._on_toggle_missing)
            sb_lay.addWidget(self.btn_toggle_missing)

            main_lay.addWidget(sub_bar)

    def _on_check_changed(self) -> None:
        if self.on_change:
            self.on_change()

    def _on_toggle_missing(self) -> None:
        self._include_missing_history = self.btn_toggle_missing.isChecked()
        if self._include_missing_history:
            self.btn_toggle_missing.setText("✓ 已包含缺失集")
            # 若主勾选框未勾，自动勾上
            if not self.chk_main.isChecked():
                self.chk_main.setChecked(True)
        else:
            self.btn_toggle_missing.setText("＋ 一并下载缺失集")
        if self.on_change:
            self.on_change()

    def _on_quality_changed(self, idx: int) -> None:
        opt = self.combo_q.currentData()
        if opt and self._current_candidate:
            self._current_candidate["quality"] = opt["quality"]
            self._current_candidate["magnet_url"] = opt["magnet"].url
            self._current_candidate["magnet_label"] = opt["magnet"].label

    def _open_detail(self) -> None:
        if self.on_open_detail:
            self.on_open_detail(self.update_item.item)

    def get_selected_tasks(self) -> list[dict]:
        """获取当前卡片最终勾选需要下载的任务列表。"""
        if not self.chk_main.isChecked():
            return []

        tasks = []
        if self._current_candidate:
            tasks.append(self._current_candidate)

        if self._include_missing_history:
            tasks.extend(self.missing_history)

        return tasks


class SubscriptionConfirmDialog(QDialog):
    """弹出汇聚所有最新订阅资源的确认弹窗（以最新一集为主，带分集详情入口）。"""

    def __init__(
        self,
        updates: list[SubscriptionUpdate | dict],
        on_confirm: Callable[[list[dict]], None],
        on_open_detail: Optional[Callable] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._raw_updates = updates
        self._on_confirm = on_confirm
        self._on_open_detail = on_open_detail
        self._cards: list[SubscriptionCard] = []

        self.setWindowTitle("🔔 发现订阅剧集最新更新")
        self.resize(760, 500)
        self._build()

    def _build(self) -> None:
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(16, 16, 16, 16)
        root_lay.setSpacing(12)

        # 头部说明
        head_lay = QVBoxLayout()
        head_lay.setSpacing(4)
        title_lbl = QLabel(f"📺 发现 <b>{len(self._raw_updates)}</b> 部订阅剧集有最新更新")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #0f172a;")
        head_lay.addWidget(title_lbl)

        sub_tip = QLabel("已默认按您的画质偏好为您挑选最新一集。点击右侧「查看全部分集」可回溯下载其它集数或版本。")
        sub_tip.setStyleSheet("font-size: 12px; color: #64748b;")
        head_lay.addWidget(sub_tip)
        root_lay.addLayout(head_lay)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        scroll_widget = QWidget()
        scroll_lay = QVBoxLayout(scroll_widget)
        scroll_lay.setContentsMargins(0, 0, 0, 0)
        scroll_lay.setSpacing(8)

        # 构建每部剧的展示卡片
        for item in self._raw_updates:
            # 兼容 SubscriptionUpdate 实例与旧式 dict
            if isinstance(item, SubscriptionUpdate):
                up = item
            else:
                # 兼容包装
                from ..models import ParseItem, Subscription
                sub = Subscription(title=item.get("sub_title", ""), detail_url=item.get("detail_url", ""))
                it = item.get("item") or ParseItem(title=item.get("sub_title", ""))
                up = SubscriptionUpdate(
                    sub=sub,
                    item=it,
                    latest_candidate=item,
                    missing_history=[],
                )

            card = SubscriptionCard(
                up,
                on_open_detail=self._on_open_detail,
                on_change=self._update_counter,
                parent=scroll_widget,
            )
            self._cards.append(card)
            scroll_lay.addWidget(card)

        scroll_lay.addStretch(1)
        scroll.setWidget(scroll_widget)
        root_lay.addWidget(scroll, 1)

        # 底部操作栏
        bottom_lay = QHBoxLayout()
        bottom_lay.setSpacing(12)

        self.chk_all = QCheckBox("全选 / 取消全选")
        self.chk_all.setChecked(True)
        self.chk_all.stateChanged.connect(self._toggle_all)
        bottom_lay.addWidget(self.chk_all)

        self.summary_lbl = QLabel("")
        self.summary_lbl.setStyleSheet("font-size: 12px; color: #64748b; font-weight: 500;")
        bottom_lay.addWidget(self.summary_lbl)

        bottom_lay.addStretch(1)

        btn_cancel = QPushButton("稍后处理")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("font-size: 13px; padding: 6px 14px;")
        btn_cancel.clicked.connect(self.reject)
        bottom_lay.addWidget(btn_cancel)

        self.btn_send = QPushButton("⚡ 立即发送下载")
        self.btn_send.setObjectName("primary")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet("""
            QPushButton#primary {
                font-size: 13px;
                font-weight: 600;
                padding: 6px 20px;
            }
        """)
        self.btn_send.clicked.connect(self._do_confirm)
        bottom_lay.addWidget(self.btn_send)

        root_lay.addLayout(bottom_lay)
        self._update_counter()

    def _toggle_all(self, state: int) -> None:
        chk = state == Qt.CheckState.Checked.value
        for card in self._cards:
            card.chk_main.setChecked(chk)
        self._update_counter()

    def _update_counter(self) -> None:
        total = 0
        for card in self._cards:
            total += len(card.get_selected_tasks())
        self.summary_lbl.setText(f"已选中 {total} 个剧集更新")
        self.btn_send.setEnabled(total > 0)

    def _do_confirm(self) -> None:
        selected_tasks = []
        for card in self._cards:
            selected_tasks.extend(card.get_selected_tasks())

        if not selected_tasks:
            self.reject()
            return

        self._on_confirm(selected_tasks)
        self.accept()
