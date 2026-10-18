import { defaultBrowserApiBase } from "./desktop_state.ts";
import { element } from "./desktop_dom.ts";

export function mountTemplate() {
  const app = element("app");
  app.innerHTML = `
  <div class="app-shell" id="appShell">
    <aside class="app-rail" id="appRail" aria-label="采集导航">
      <div class="brand" data-window-drag>
        <button id="toggleSidebar" class="shell-rail-toggle" aria-label="收起侧栏" aria-expanded="true" aria-controls="appRail" title="收起侧栏"><span data-icon="sidebar"></span><span class="brand-mark toggle-mark" aria-hidden="true"></span></button>
        <span class="brand-mark product-mark" aria-hidden="true"></span><strong class="product-name">Crow</strong>
      </div>
      <nav class="stage-nav" aria-label="主导航">
        <button id="openCollection" class="active" aria-label="采集" title="采集" aria-pressed="true" aria-controls="collectionPage"><span data-icon="links"></span><span class="nav-label">采集</span></button>
      </nav>
      <div class="rail-footer">
        <button id="openSettings" aria-label="设置" title="设置" aria-pressed="false" aria-controls="settingsPage"><span data-icon="settings"></span><span class="nav-label">设置</span></button>
      </div>
    </aside>
    <div class="app-workspace">
      <header class="app-topbar">
        <div class="titlebar-drag" data-window-drag><button id="closeSettings" class="window-control hidden" aria-label="返回采集" title="返回采集"><span data-icon="back"></span></button></div>
        <div class="window-controls">
          <button id="windowRefresh" class="window-control window-refresh" aria-label="刷新" title="刷新"><span data-icon="refresh"></span></button>
          <button class="window-control hidden" data-window-command="minimize" aria-label="最小化" title="最小化"><span data-icon="minimize"></span></button>
          <button class="window-control hidden" data-window-command="maximize" aria-label="最大化或还原" title="最大化或还原"><span data-icon="maximize"></span></button>
          <button class="window-control window-close hidden" data-window-command="close" aria-label="关闭窗口" title="关闭窗口"><span data-icon="close"></span></button>
        </div>
      </header>
      <main>
    <div id="shellNotice" class="overview-notice hidden" role="alert"></div>
    <div id="collectionPage">
      <div class="workspace-heading">
        <h1 id="workspaceTitle">采集</h1>
        <div class="workspace-actions"><button id="refresh" class="primary-button">刷新数据</button></div>
      </div>
    <div id="overviewNotice" class="overview-notice hidden" role="alert"></div>
    <section class="cards" id="cards" aria-label="运行与采集指标"><div class="empty-state">正在读取运行与采集指标...</div></section>
    <section class="collection-workspace" id="collectionWorkspace" aria-labelledby="workspaceTitle">
    <section class="panel region-panel">
      <div class="collection-stage-tabs" role="group" aria-label="完成阶段筛选">
        <button data-stage="links" class="active" aria-pressed="true" aria-controls="contentLayout" title="已采集链接，尚未采集详情">链接</button>
        <button data-stage="details" aria-pressed="false" aria-controls="contentLayout" title="已采集详情，尚未完成分析">详情</button>
        <button data-stage="analysis" aria-pressed="false" aria-controls="contentLayout" title="已完成分析">分析</button>
      </div>
      <div class="region-header">
        <div>
          <strong>所在地</strong>
          <span class="status-line" id="regionSelection" role="status">全部地区</span>
        </div>
        <div class="region-actions">
          <button id="toggleRegions" aria-expanded="false" aria-controls="regionFilters">筛选地区</button>
          <button id="refreshRegions" aria-label="刷新地区" title="刷新地区"><span data-icon="refresh"></span></button>
          <button id="resetRegionLinks" class="danger-button hidden">重置本地区链接采集</button>
        </div>
      </div>
      <div id="regionFilters" class="hidden">
      <div class="region-level">
        <div class="region-level-title">省份</div>
        <div class="region-tabs" id="provinceTabs"></div>
      </div>
      <div class="region-level">
        <div class="region-level-title">城市</div>
        <div class="region-tabs" id="cityTabs"></div>
      </div>
      <div class="region-level">
        <div class="region-level-title">地区</div>
        <div class="region-tabs" id="districtTabs"></div>
      </div>
      </div>
    </section>
    <div class="toolbar list-toolbar">
      <label>每页 <select id="limit"><option selected>10</option><option>20</option><option>50</option></select></label>
      <button id="prev" disabled>上一页</button>
      <button id="next" disabled>下一页</button>
      <span class="status-line" id="listStatus" role="status"></span>
    </div>
    <section class="layout detail-hidden" id="contentLayout">
      <div class="panel table-wrap" aria-label="采集商品列表" tabindex="0">
        <table aria-label="采集商品">
          <thead><tr><th>商品编号</th><th>链接</th><th>地区</th><th>状态</th></tr></thead>
          <tbody id="items"><tr><td colspan="4" class="empty-state">正在读取商品列表...</td></tr></tbody>
        </table>
      </div>
      <aside class="panel detail hidden" id="detailPanel">
        <div class="detail-heading"><h2 id="detailTitle">已采集 HTML 文本</h2><button id="closeDetail" aria-label="关闭详情面板">关闭</button></div>
        <p class="status-line" id="detailHint">商品详情页采集完成后保存的 HTML/文本内容，用于后续 AI 分析。</p>
        <div class="detail-actions hidden" id="analysisActions">
          <span class="analysis-count" id="analysisAttemptCount">AI 分析次数：-</span>
          <button id="reanalysisButton">AI 再分析</button>
          <button id="editButton">手动编辑</button>
          <button id="manualUpdateButton" class="primary-button hidden">手动更新</button>
        </div>
        <div class="status-line" id="detailPath" role="status"></div>
        <div class="detail-action-status hidden" id="detailActionStatus" role="status" aria-live="polite"></div>
        <pre id="detailHtmlText">点击“商品详情页采集”中的任一商品查看。</pre>
        <div class="standardized-rows hidden" id="standardizedRows"></div>
      </aside>
    </section>
    </section>
    </div>
    <section class="settings-page hidden" id="settingsPage" aria-labelledby="settingsTitle">
      <h1 id="settingsTitle" tabindex="-1">设置</h1>
      <details class="panel connection-panel" id="connectionSettings" open>
        <summary><span data-icon="settings"></span><strong>API 连接</strong></summary>
        <div class="settings-body">
          <div class="toolbar"><label>API 地址 <input id="apiBase" class="api-base" value="${defaultBrowserApiBase()}" /></label><button id="applyApiBase">应用地址</button></div>
          <div class="toolbar"><label>控制授权 <input id="restartToken" type="password" autocomplete="off" placeholder="仅保存在当前窗口，不写入磁盘" /></label></div>
          <p class="status-line" id="connectionStatus" role="status">读取默认 API 地址中...</p>
        </div>
      </details>
      <details class="panel connection-panel" id="runtimeSettings"></details>
      <details class="panel connection-panel">
        <summary><span data-icon="refresh"></span><strong>数据刷新</strong></summary>
        <div class="settings-body">
          <p class="status-line" id="autoRefreshStatus" role="status">每 60 秒自动刷新</p>
          <p class="status-line" id="regionRefreshStatus" role="status">每 10 分钟自动刷新所在地状态</p>
        </div>
      </details>
    </section>
  </main>
    </div>
  </div>
  <dialog class="auth-dialog" id="authChallengeDialog" aria-label="人工认证">
    <div class="auth-dialog-toolbar">
      <button id="authChallengeEdge" autofocus>在常用 Edge 中认证</button>
      <button id="authChallengeReload">打开专用认证浏览器</button>
      <button id="authChallengeResume" class="primary-button">已完成挑战</button>
    </div>
    <div class="status-line" id="authChallengeStatus" role="status" aria-live="polite"></div>
  </dialog>
  <dialog class="confirm-dialog" id="regionResetDialog" aria-labelledby="regionResetTitle" aria-describedby="regionResetDescription">
    <h2 id="regionResetTitle">重置地区链接采集？</h2>
    <p id="regionResetDescription"></p>
    <form method="dialog"><button value="cancel" autofocus>取消</button><button value="confirm" class="danger-button">确认重置</button></form>
  </dialog>
  <dialog class="confirm-dialog" id="engineRestartDialog" aria-labelledby="engineRestartTitle">
    <h2 id="engineRestartTitle">重启 PC2 采集引擎？</h2>
    <p>将通过 NAS 请求 PC2 重启链接、详情和分析 Worker，并继续采集。不会重启整台电脑、删除商品数据或关闭认证浏览器；尚未解决的挑战仍需认证。</p>
    <form method="dialog"><button value="cancel" autofocus>取消</button><button value="confirm" class="danger-button">确认重启</button></form>
  </dialog>
`;
}
