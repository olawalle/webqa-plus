"""Visual overlay injection for visual mode."""

import html
import json
from typing import Any, Dict, List, Optional

from playwright.async_api import Page


OVERLAY_CSS = """
/* WebQA-Plus Overlay Styles */
#webqa-plus-overlay {
    position: fixed;
    bottom: 10px;
    right: 10px;
    width: 320px;
    background: rgba(30, 30, 40, 0.95);
    border: 2px solid #3b82f6;
    border-radius: 8px;
    padding: 16px;
    color: #ffffff;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px;
    z-index: 2147483647;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(10px);
    pointer-events: auto;
    user-select: text;
    max-height: 400px;
    overflow-y: auto;
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
}

#webqa-plus-overlay .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

#webqa-plus-overlay .header-left {
    display: flex;
    align-items: center;
    gap: 8px;
}

#webqa-plus-overlay .collapse-button {
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.08);
    color: #e5e7eb;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
}

#webqa-plus-overlay .overlay-body {
    display: block;
}

#webqa-plus-overlay.collapsed .overlay-body {
    display: none;
}

#webqa-plus-overlay.collapsed {
    width: 210px;
    max-height: 80px;
    overflow: hidden;
}

#webqa-plus-overlay .logo {
    width: 24px;
    height: 24px;
    background: #3b82f6;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
}

#webqa-plus-overlay .title {
    font-weight: 600;
    font-size: 14px;
    color: #3b82f6;
}

#webqa-plus-overlay .status {
    font-size: 13px;
    margin-bottom: 12px;
}

#webqa-plus-overlay .phase {
    font-size: 12px;
    color: #93c5fd;
    margin-top: 4px;
}

#webqa-plus-overlay .objective {
    font-size: 12px;
    color: #d1d5db;
    margin-top: 8px;
    padding: 8px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
}

#webqa-plus-overlay .directive-panel {
    margin-top: 10px;
    padding: 10px;
    border-radius: 8px;
    background: rgba(15, 23, 42, 0.55);
    border: 1px solid rgba(59, 130, 246, 0.22);
}

#webqa-plus-overlay .directive-row {
    display: flex;
    gap: 8px;
    margin-top: 6px;
}

#webqa-plus-overlay .directive-input {
    flex: 1;
    min-width: 0;
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.14);
    background: rgba(255, 255, 255, 0.08);
    color: #f8fafc;
    padding: 8px 10px;
    font-size: 12px;
    outline: none;
}

#webqa-plus-overlay .directive-input::placeholder {
    color: #94a3b8;
}

#webqa-plus-overlay .directive-input:focus {
    border-color: rgba(96, 165, 250, 0.8);
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

#webqa-plus-overlay .directive-button {
    border: 0;
    border-radius: 6px;
    background: linear-gradient(135deg, #2563eb, #0ea5e9);
    color: #ffffff;
    padding: 8px 10px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
}

#webqa-plus-overlay .directive-button:disabled {
    opacity: 0.65;
    cursor: wait;
}

#webqa-plus-overlay .directive-status {
    margin-top: 8px;
    min-height: 16px;
    font-size: 11px;
    color: #93c5fd;
}

#webqa-plus-overlay .flow-name {
    color: #10b981;
    font-weight: 500;
}

#webqa-plus-overlay .progress-container {
    margin: 12px 0;
}

#webqa-plus-overlay .progress-label {
    font-size: 12px;
    color: #9ca3af;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
}

#webqa-plus-overlay .progress-bar {
    height: 6px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 3px;
    overflow: hidden;
}

#webqa-plus-overlay .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #3b82f6, #10b981);
    border-radius: 3px;
    transition: width 0.3s ease;
}

#webqa-plus-overlay .section {
    margin-top: 12px;
}

#webqa-plus-overlay .section-title {
    font-size: 11px;
    text-transform: uppercase;
    color: #6b7280;
    margin-bottom: 6px;
    letter-spacing: 0.5px;
}

#webqa-plus-overlay .flow-list {
    list-style: none;
    padding: 0;
    margin: 0;
}

#webqa-plus-overlay .flow-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    margin-bottom: 4px;
    opacity: 0.7;
}

#webqa-plus-overlay .flow-item.completed {
    opacity: 1;
    color: #10b981;
}

#webqa-plus-overlay .flow-item.current {
    opacity: 1;
    color: #3b82f6;
    font-weight: 500;
}

#webqa-plus-overlay .flow-item.upcoming {
    color: #6b7280;
}

#webqa-plus-overlay .icon {
    font-size: 10px;
}

#webqa-plus-overlay .stats {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
}

#webqa-plus-overlay .stat {
    text-align: center;
}

#webqa-plus-overlay .stat-value {
    font-size: 18px;
    font-weight: 700;
    color: #3b82f6;
}

#webqa-plus-overlay .stat-label {
    font-size: 10px;
    color: #6b7280;
    text-transform: uppercase;
}

#webqa-plus-overlay .action-log {
    max-height: 60px;
    overflow-y: auto;
    font-size: 11px;
    color: #9ca3af;
    margin-top: 8px;
}

#webqa-plus-overlay .action-item {
    padding: 2px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

#webqa-plus-pointer {
    position: fixed;
    top: 0;
    left: 0;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: rgba(59, 130, 246, 0.9);
    border: 2px solid rgba(255, 255, 255, 0.9);
    transform: translate3d(-100px, -100px, 0);
    z-index: 2147483646;
    pointer-events: none;
    transition: transform 40ms linear;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.25);
}

#webqa-plus-pointer-click {
    position: fixed;
    top: 0;
    left: 0;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    border: 2px solid rgba(16, 185, 129, 0.85);
    transform: translate3d(-100px, -100px, 0) scale(0.6);
    opacity: 0;
    z-index: 2147483645;
    pointer-events: none;
}

#webqa-plus-pointer-click.active {
    animation: webqa-pointer-ripple 360ms ease-out;
}

@keyframes webqa-pointer-ripple {
    0% {
        opacity: 0.95;
        transform: translate3d(var(--x), var(--y), 0) scale(0.6);
    }
    100% {
        opacity: 0;
        transform: translate3d(var(--x), var(--y), 0) scale(2.25);
    }
}
"""

OVERLAY_HTML_TEMPLATE = """
<div id="webqa-plus-overlay">
    <div class="header">
        <div class="header-left">
            <div class="logo">🧪</div>
            <div class="title">WebQA-Plus</div>
        </div>
        <button id="webqa-plus-collapse-toggle" class="collapse-button" type="button" aria-expanded="true">Collapse</button>
    </div>

    <div class="overlay-body" id="webqa-plus-overlay-body">
    <div class="status">
        Currently testing: <span class="flow-name" id="current-flow">{flow_name}</span>
        <div class="phase">Phase: <span id="current-phase">{current_phase}</span></div>
    </div>

    <div class="objective" id="objective-text">{objective_text}</div>
    <div class="directive-panel">
        <div class="section-title">Steer Test Live</div>
        <div class="directive-row">
            <input id="webqa-plus-directive-input" class="directive-input" type="text" placeholder="Tell the agent what to test next" value="{directive_value}" />
            <button id="webqa-plus-directive-button" class="directive-button" type="button">Update</button>
        </div>
        <div class="directive-status" id="directive-status">Update the objective without leaving this page.</div>
    </div>
    
    <div class="progress-container">
        <div class="progress-label">
            <span>Progress</span>
            <span id="progress-text">{current_step}/{max_steps}</span>
        </div>
        <div class="progress-bar">
            <div class="progress-fill" id="progress-bar" style="width: {progress_pct}%;"></div>
        </div>
    </div>
    
    <div class="section">
        <div class="section-title">Completed Flows</div>
        <ul class="flow-list" id="completed-flows">
            {completed_flows}
        </ul>
    </div>
    
    <div class="section">
        <div class="section-title">Upcoming Flows</div>
        <ul class="flow-list" id="upcoming-flows">
            {upcoming_flows}
        </ul>
    </div>
    
    <div class="stats">
        <div class="stat">
            <div class="stat-value" id="stat-urls">{url_count}</div>
            <div class="stat-label">Pages</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="stat-coverage">{coverage:.0f}%</div>
            <div class="stat-label">Coverage</div>
        </div>
    </div>
    
    <div class="action-log" id="action-log"></div>
    </div>
</div>
"""


class VisualOverlay:
    """Manages the visual overlay in the browser."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize overlay manager."""
        self.config = config
        self.is_visible = False
        self._init_script_installed = False
        self._latest_state: Dict[str, Any] = {
            "flow_name": "Initializing...",
            "current_phase": "idle",
            "objective_text": "No objective set.",
            "current_step": 0,
            "max_steps": 100,
            "completed_flows": [],
            "upcoming_flows": [],
            "url_count": 0,
            "coverage": 0.0,
        }

    def _set_latest_state(
        self,
        *,
        flow_name: str,
        current_phase: str,
        objective_text: str,
        current_step: int,
        max_steps: int,
        completed_flows: List[str],
        upcoming_flows: List[str],
        url_count: int,
        coverage: float,
    ) -> None:
        """Cache the latest overlay payload so reinjection stays live."""
        self._latest_state = {
            "flow_name": flow_name,
            "current_phase": current_phase,
            "objective_text": objective_text,
            "current_step": current_step,
            "max_steps": max_steps,
            "completed_flows": list(completed_flows),
            "upcoming_flows": list(upcoming_flows),
            "url_count": url_count,
            "coverage": coverage,
        }

    def _render_latest_overlay(self) -> str:
        """Render overlay HTML from cached state."""
        return self._render_overlay(**self._latest_state)

    def _latest_js_state(self) -> Dict[str, Any]:
        """Build the browser-side overlay state payload."""
        return {
            "flowName": self._latest_state.get("flow_name", "Initializing..."),
            "currentPhase": self._latest_state.get("current_phase", "idle"),
            "objective": self._latest_state.get("objective_text", ""),
            "currentStep": self._latest_state.get("current_step", 0),
            "maxSteps": self._latest_state.get("max_steps", 100),
            "completedFlows": list(self._latest_state.get("completed_flows", [])),
            "upcomingFlows": list(self._latest_state.get("upcoming_flows", [])),
            "urlCount": self._latest_state.get("url_count", 0),
            "coverage": self._latest_state.get("coverage", 0),
            "collapsed": False,
            "actions": [],
        }

    def _overlay_position(self) -> str:
        """Return validated overlay position value."""
        position = str(self.config.get("overlay_position", "bottom-right")).strip().lower()
        return position if position in {"top-right", "top-left", "bottom-right", "bottom-left"} else "bottom-right"

    def _overlay_opacity(self) -> float:
        """Return clamped overlay opacity."""
        try:
            value = float(self.config.get("overlay_opacity", 0.9))
        except Exception:
            value = 0.9
        return max(0.25, min(1.0, value))

    async def _install_init_script(self, page: Page, initial_html: str) -> None:
        """Install init script so overlay is re-injected on every navigation."""
        if self._init_script_installed:
            return

        css = json.dumps(OVERLAY_CSS)
        html = json.dumps(initial_html)
        state = json.dumps(self._latest_js_state())
        position = json.dumps(self._overlay_position())
        opacity = self._overlay_opacity()
        await page.context.add_init_script(
            script=f"""
                (() => {{
                    const OVERLAY_ID = 'webqa-plus-overlay';
                    const STYLE_ID = 'webqa-plus-overlay-style';
                    const POINTER_ID = 'webqa-plus-pointer';
                    const POINTER_CLICK_ID = 'webqa-plus-pointer-click';
                    const overlayCss = {css};
                    const overlayHtml = {html};
                    const overlayState = {state};
                    const overlayPosition = {position};
                    const overlayOpacity = {opacity};
                    const STATE_KEY = '__webqa_overlay_observer__';
                    const POINTER_STATE_KEY = '__webqa_overlay_pointer_bound__';

                    const applyOverlayPosition = (overlay) => {{
                        if (!overlay) return;
                        overlay.style.top = 'auto';
                        overlay.style.bottom = 'auto';
                        overlay.style.left = 'auto';
                        overlay.style.right = 'auto';

                        if (overlayPosition === 'top-left') {{
                            overlay.style.top = '10px';
                            overlay.style.left = '10px';
                        }} else if (overlayPosition === 'top-right') {{
                            overlay.style.top = '10px';
                            overlay.style.right = '10px';
                        }} else if (overlayPosition === 'bottom-left') {{
                            overlay.style.bottom = '10px';
                            overlay.style.left = '10px';
                        }} else {{
                            overlay.style.bottom = '10px';
                            overlay.style.right = '10px';
                        }}
                        overlay.style.opacity = String(overlayOpacity);
                    }};

                    const installDirectiveControls = () => {{
                        const input = document.getElementById('webqa-plus-directive-input');
                        const button = document.getElementById('webqa-plus-directive-button');
                        const status = document.getElementById('directive-status');
                        const objectiveEl = document.getElementById('objective-text');

                        if (!input || !button || !status) return;
                        if (button.dataset.bound === 'true') return;

                        const setStatus = (message) => {{
                            status.textContent = message;
                        }};

                        const submitDirective = async () => {{
                            const instruction = input.value.trim();
                            if (!instruction) {{
                                setStatus('Enter a directive first.');
                                input.focus();
                                return;
                            }}

                            if (typeof window.webqaPlusUpdateDirective !== 'function') {{
                                setStatus('Live steering is unavailable on this run.');
                                return;
                            }}

                            button.disabled = true;
                            setStatus('Updating objective...');

                            try {{
                                const result = await window.webqaPlusUpdateDirective(instruction);
                                if (result && result.ok === false) {{
                                    throw new Error(result.error || 'Failed to update objective.');
                                }}

                                window.webqaState = window.webqaState || {{ actions: [] }};
                                window.webqaState.objective = instruction;
                                if (objectiveEl) objectiveEl.textContent = instruction;
                                setStatus('Objective updated.');
                            }} catch (error) {{
                                const message = error && error.message ? error.message : 'Directive update failed.';
                                setStatus(message);
                            }} finally {{
                                button.disabled = false;
                            }}
                        }};

                        button.addEventListener('click', (event) => {{
                            event.preventDefault();
                            event.stopPropagation();
                            void submitDirective();
                        }});

                        input.addEventListener('keydown', (event) => {{
                            if (event.key !== 'Enter') return;
                            event.preventDefault();
                            event.stopPropagation();
                            void submitDirective();
                        }});

                        if (!input.value && window.webqaState && window.webqaState.objective) {{
                            input.value = window.webqaState.objective;
                        }}

                        button.dataset.bound = 'true';
                    }};

                    const installCollapseControls = () => {{
                        const overlay = document.getElementById(OVERLAY_ID);
                        const toggle = document.getElementById('webqa-plus-collapse-toggle');
                        if (!overlay || !toggle) return;
                        if (toggle.dataset.bound === 'true') return;

                        const applyState = () => {{
                            const collapsed = overlay.classList.contains('collapsed');
                            toggle.textContent = collapsed ? 'Expand' : 'Collapse';
                            toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                        }};

                        if (window.webqaState && window.webqaState.collapsed) {{
                            overlay.classList.add('collapsed');
                        }}

                        toggle.addEventListener('click', (event) => {{
                            event.preventDefault();
                            event.stopPropagation();
                            overlay.classList.toggle('collapsed');
                            window.webqaState = window.webqaState || {{ actions: [] }};
                            window.webqaState.collapsed = overlay.classList.contains('collapsed');
                            applyState();
                        }});

                        applyState();
                        toggle.dataset.bound = 'true';
                    }};

                    const ensureOverlay = () => {{
                        if (!document.head) return;

                        if (!document.getElementById(STYLE_ID)) {{
                            const style = document.createElement('style');
                            style.id = STYLE_ID;
                            style.textContent = overlayCss;
                            document.head.appendChild(style);
                        }}

                        if (!document.getElementById(OVERLAY_ID) && document.body) {{
                            const wrapper = document.createElement('div');
                            wrapper.innerHTML = overlayHtml;
                            const node = wrapper.firstElementChild;
                            if (node) document.body.appendChild(node);
                        }}

                        if (!document.getElementById(POINTER_ID) && document.body) {{
                            const pointer = document.createElement('div');
                            pointer.id = POINTER_ID;
                            document.body.appendChild(pointer);
                        }}

                        if (!document.getElementById(POINTER_CLICK_ID) && document.body) {{
                            const clickPulse = document.createElement('div');
                            clickPulse.id = POINTER_CLICK_ID;
                            document.body.appendChild(clickPulse);
                        }}

                        const overlay = document.getElementById(OVERLAY_ID);
                        if (overlay) {{
                            applyOverlayPosition(overlay);
                            overlay.style.display = 'block';
                            overlay.style.visibility = 'visible';
                        }}

                        if (!window.webqaState) {{
                            window.webqaState = {{ ...overlayState }};
                        }}

                        installDirectiveControls();
                        installCollapseControls();
                    }};

                    const installObserver = () => {{
                        if (!document.body || window[STATE_KEY]) return;
                        const observer = new MutationObserver(() => ensureOverlay());
                        observer.observe(document.body, {{ childList: true, subtree: true }});
                        window[STATE_KEY] = true;
                    }};

                    const installPointerTracking = () => {{
                        if (!document.body || window[POINTER_STATE_KEY]) return;

                        const positionPointer = (x, y) => {{
                            const pointer = document.getElementById(POINTER_ID);
                            if (pointer) {{
                                pointer.style.transform = `translate3d(${{x - 6}}px, ${{y - 6}}px, 0)`;
                            }}
                        }};

                        const pulseClick = (x, y) => {{
                            const clickPulse = document.getElementById(POINTER_CLICK_ID);
                            if (!clickPulse) return;
                            clickPulse.style.setProperty('--x', `${{x - 9}}px`);
                            clickPulse.style.setProperty('--y', `${{y - 9}}px`);
                            clickPulse.classList.remove('active');
                            void clickPulse.offsetWidth;
                            clickPulse.classList.add('active');
                        }};

                        window.addEventListener('mousemove', (event) => {{
                            positionPointer(event.clientX, event.clientY);
                        }}, {{ passive: true }});

                        window.addEventListener('click', (event) => {{
                            positionPointer(event.clientX, event.clientY);
                            pulseClick(event.clientX, event.clientY);
                        }}, {{ passive: true }});

                        window[POINTER_STATE_KEY] = true;
                    }};

                    if (document.readyState === 'loading') {{
                        document.addEventListener('DOMContentLoaded', () => {{
                            ensureOverlay();
                            installObserver();
                            installPointerTracking();
                        }}, {{ once: true }});
                    }} else {{
                        ensureOverlay();
                        installObserver();
                        installPointerTracking();
                    }}
                }})();
            """
        )
        self._init_script_installed = True

    async def inject(self, page: Page) -> None:
        """Inject the overlay into the page."""
        # Add latest HTML so reinjection reflects current live state.
        initial_html = self._render_latest_overlay()

        await self._install_init_script(page, initial_html)

        # Add CSS
        await page.add_style_tag(content=OVERLAY_CSS)

        browser_state = json.dumps(self._latest_js_state())
        overlay_position = self._overlay_position()
        overlay_opacity = self._overlay_opacity()

        await page.evaluate(f"""
            (() => {{
                // Remove existing overlay if present
                const existing = document.getElementById('webqa-plus-overlay');
                if (existing) existing.remove();
                
                // Inject new overlay
                const div = document.createElement('div');
                div.innerHTML = `{initial_html}`;
                document.body.appendChild(div.firstElementChild);
                
                // Store state globally
                const previousActions = Array.isArray(window.webqaState?.actions)
                    ? window.webqaState.actions
                    : [];
                const previousCollapsed = Boolean(window.webqaState?.collapsed);
                window.webqaState = {{ ...{browser_state}, actions: previousActions }};
                window.webqaState.collapsed = previousCollapsed;

                const overlay = document.getElementById('webqa-plus-overlay');
                if (overlay) {{
                    overlay.style.top = 'auto';
                    overlay.style.bottom = 'auto';
                    overlay.style.left = 'auto';
                    overlay.style.right = 'auto';
                    if ({json.dumps(overlay_position)} === 'top-left') {{
                        overlay.style.top = '10px';
                        overlay.style.left = '10px';
                    }} else if ({json.dumps(overlay_position)} === 'top-right') {{
                        overlay.style.top = '10px';
                        overlay.style.right = '10px';
                    }} else if ({json.dumps(overlay_position)} === 'bottom-left') {{
                        overlay.style.bottom = '10px';
                        overlay.style.left = '10px';
                    }} else {{
                        overlay.style.bottom = '10px';
                        overlay.style.right = '10px';
                    }}
                    overlay.style.opacity = String({overlay_opacity});
                    if (window.webqaState.collapsed) {{
                        overlay.classList.add('collapsed');
                    }}
                }}

                const input = document.getElementById('webqa-plus-directive-input');
                const button = document.getElementById('webqa-plus-directive-button');
                const status = document.getElementById('directive-status');
                const objectiveEl = document.getElementById('objective-text');
                const collapseToggle = document.getElementById('webqa-plus-collapse-toggle');

                const setStatus = (message) => {{
                    if (status) status.textContent = message;
                }};

                const submitDirective = async () => {{
                    const instruction = (input?.value || '').trim();
                    if (!instruction) {{
                        setStatus('Enter a directive first.');
                        input?.focus();
                        return;
                    }}

                    if (typeof window.webqaPlusUpdateDirective !== 'function') {{
                        setStatus('Live steering is unavailable on this run.');
                        return;
                    }}

                    if (button) button.disabled = true;
                    setStatus('Updating objective...');

                    try {{
                        const result = await window.webqaPlusUpdateDirective(instruction);
                        if (result && result.ok === false) {{
                            throw new Error(result.error || 'Failed to update objective.');
                        }}
                        window.webqaState.objective = instruction;
                        if (objectiveEl) objectiveEl.textContent = instruction;
                        setStatus('Objective updated.');
                    }} catch (error) {{
                        const message = error && error.message ? error.message : 'Directive update failed.';
                        setStatus(message);
                    }} finally {{
                        if (button) button.disabled = false;
                    }}
                }};

                if (input && !input.value && window.webqaState.objective) {{
                    input.value = window.webqaState.objective;
                }}

                if (button && button.dataset.bound !== 'true') {{
                    button.addEventListener('click', (event) => {{
                        event.preventDefault();
                        event.stopPropagation();
                        void submitDirective();
                    }});
                    button.dataset.bound = 'true';
                }}

                if (input && input.dataset.bound !== 'true') {{
                    input.addEventListener('keydown', (event) => {{
                        if (event.key !== 'Enter') return;
                        event.preventDefault();
                        event.stopPropagation();
                        void submitDirective();
                    }});
                    input.dataset.bound = 'true';
                }}

                if (collapseToggle && collapseToggle.dataset.bound !== 'true') {{
                    const refreshCollapseLabel = () => {{
                        const isCollapsed = overlay?.classList.contains('collapsed');
                        collapseToggle.textContent = isCollapsed ? 'Expand' : 'Collapse';
                        collapseToggle.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
                    }};

                    collapseToggle.addEventListener('click', (event) => {{
                        event.preventDefault();
                        event.stopPropagation();
                        if (!overlay) return;
                        overlay.classList.toggle('collapsed');
                        window.webqaState.collapsed = overlay.classList.contains('collapsed');
                        refreshCollapseLabel();
                    }});

                    refreshCollapseLabel();
                    collapseToggle.dataset.bound = 'true';
                }}
            }})();
        """)

        self.is_visible = True

    async def update(
        self,
        page: Page,
        flow_name: str,
        current_phase: str,
        objective_text: str,
        current_step: int,
        max_steps: int,
        completed_flows: List[str],
        upcoming_flows: List[str],
        url_count: int,
        coverage: float,
        current_action: Optional[str] = None,
    ) -> None:
        """Update the overlay with new state."""
        if not self.is_visible:
            return

        self._set_latest_state(
            flow_name=flow_name,
            current_phase=current_phase,
            objective_text=objective_text,
            current_step=current_step,
            max_steps=max_steps,
            completed_flows=completed_flows,
            upcoming_flows=upcoming_flows,
            url_count=url_count,
            coverage=coverage,
        )

        async def _apply_update() -> None:
            await page.evaluate(f"""
                (() => {{
                    const overlay = document.getElementById('webqa-plus-overlay');
                    if (!overlay) {{
                        throw new Error('overlay-missing');
                    }}
                    const phaseProbe = document.getElementById('current-phase');
                    const directiveProbe = document.getElementById('webqa-plus-directive-input');
                    if (!phaseProbe || !directiveProbe) {{
                        throw new Error('overlay-stale-template');
                    }}

                    if (!window.webqaState) {{
                        window.webqaState = {{ actions: [] }};
                    }}
                    if (!Array.isArray(window.webqaState.actions)) {{
                        window.webqaState.actions = [];
                    }}
                    window.webqaState.flowName = {json.dumps(flow_name)};
                    window.webqaState.currentPhase = {json.dumps(current_phase)};
                    window.webqaState.objective = {json.dumps(objective_text)};
                    window.webqaState.currentStep = {current_step};
                    window.webqaState.maxSteps = {max_steps};
                    window.webqaState.completedFlows = {json.dumps(completed_flows)};
                    window.webqaState.upcomingFlows = {json.dumps(upcoming_flows)};
                    window.webqaState.urlCount = {url_count};
                    window.webqaState.coverage = {coverage};
                    
                    // Update flow name
                    const flowEl = document.getElementById('current-flow');
                    if (flowEl) flowEl.textContent = {json.dumps(flow_name)};

                    // Update phase + objective
                    const phaseEl = document.getElementById('current-phase');
                    if (phaseEl) phaseEl.textContent = {json.dumps(current_phase)};
                    const objectiveEl = document.getElementById('objective-text');
                    if (objectiveEl) objectiveEl.textContent = {json.dumps(objective_text)};
                    const directiveInput = document.getElementById('webqa-plus-directive-input');
                    if (directiveInput && document.activeElement !== directiveInput) {{
                        directiveInput.value = {json.dumps(objective_text if objective_text != 'No objective set.' else '')};
                    }}
                    
                    // Update progress
                    const progressText = document.getElementById('progress-text');
                    const progressBar = document.getElementById('progress-bar');
                    if (progressText) progressText.textContent = `{current_step}/{max_steps}`;
                    if (progressBar) progressBar.style.width = `${{max_steps > 0 ? (current_step / max_steps) * 100 : 0}}%`;
                    
                    // Update completed flows
                    const completedEl = document.getElementById('completed-flows');
                    if (completedEl) {{
                        completedEl.innerHTML = {json.dumps(completed_flows)}.map(f => 
                            `<li class="flow-item completed"><span class="icon">✅</span> ${f}</li>`
                        ).join('') || '<li class="flow-item">None yet</li>';
                    }}
                    
                    // Update upcoming flows
                    const upcomingEl = document.getElementById('upcoming-flows');
                    if (upcomingEl) {{
                        upcomingEl.innerHTML = {json.dumps(upcoming_flows)}.map(f => 
                            `<li class="flow-item upcoming"><span class="icon">○</span> ${f}</li>`
                        ).join('') || '<li class="flow-item">None remaining</li>';
                    }}
                    
                    // Update stats
                    const urlStat = document.getElementById('stat-urls');
                    const coverageStat = document.getElementById('stat-coverage');
                    if (urlStat) urlStat.textContent = `{url_count}`;
                    if (coverageStat) coverageStat.textContent = `{coverage:.0f}%`;
                    
                    // Update action log
                    if ({json.dumps(current_action)}) {{
                        window.webqaState.actions.unshift({json.dumps(current_action)});
                        if (window.webqaState.actions.length > 3) {{
                            window.webqaState.actions.pop();
                        }}
                        const logEl = document.getElementById('action-log');
                        if (logEl) {{
                            logEl.innerHTML = window.webqaState.actions.map(a => 
                                `<div class="action-item">▶ ${a}</div>`
                            ).join('');
                        }}
                    }}
                }})();
            """)

        for _ in range(2):
            try:
                await _apply_update()
                return
            except Exception:
                await self.inject(page)

    async def hide(self, page: Page) -> None:
        """Hide the overlay."""
        if not self.is_visible:
            return

        try:
            await page.evaluate("""
                (() => {
                    const overlay = document.getElementById('webqa-plus-overlay');
                    if (overlay) overlay.style.display = 'none';
                })();
            """)
            self.is_visible = False
        except:
            pass

    async def show(self, page: Page) -> None:
        """Show the overlay."""
        try:
            await page.evaluate("""
                (() => {
                    const overlay = document.getElementById('webqa-plus-overlay');
                    if (overlay) overlay.style.display = 'block';
                })();
            """)
            self.is_visible = True
        except:
            pass

    def _render_overlay(
        self,
        flow_name: str,
        current_phase: str,
        objective_text: str,
        current_step: int,
        max_steps: int,
        completed_flows: List[str],
        upcoming_flows: List[str],
        url_count: int,
        coverage: float,
    ) -> str:
        """Render the overlay HTML."""
        progress_pct = (current_step / max_steps) * 100 if max_steps > 0 else 0

        completed_html = (
            "\n".join(
                f'<li class="flow-item completed"><span class="icon">✅</span> {f}</li>'
                for f in (completed_flows or [])
            )
            or '<li class="flow-item">None yet</li>'
        )

        upcoming_html = (
            "\n".join(
                f'<li class="flow-item upcoming"><span class="icon">○</span> {f}</li>'
                for f in (upcoming_flows or [])
            )
            or '<li class="flow-item">None remaining</li>'
        )

        return OVERLAY_HTML_TEMPLATE.format(
            flow_name=flow_name,
            current_phase=current_phase,
            objective_text=objective_text,
            directive_value=html.escape(objective_text if objective_text != "No objective set." else "", quote=True),
            current_step=current_step,
            max_steps=max_steps,
            progress_pct=progress_pct,
            completed_flows=completed_html,
            upcoming_flows=upcoming_html,
            url_count=url_count,
            coverage=coverage,
        )
