// Telegram Mini App + API base (from ?api= or same origin)
const API_BASE = (typeof window !== 'undefined' && window.API_BASE) ? window.API_BASE : '';
// Заголовок для ngrok: иначе бесплатный ngrok отдаёт HTML "Visit Site" вместо JSON
function apiHeaders(extra) {
    const h = { ...(extra || {}) };
    if (API_BASE && API_BASE.includes('ngrok')) h['ngrok-skip-browser-warning'] = 'true';
    return h;
}
if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
    var tp = window.Telegram.WebApp.themeParams;
    if (tp && (tp.bg_color || tp.secondary_bg_color)) {
        var r = document.documentElement;
        if (tp.bg_color) r.style.setProperty('--bg-primary', tp.bg_color);
        if (tp.secondary_bg_color) r.style.setProperty('--bg-secondary', tp.secondary_bg_color);
        if (tp.text_color) r.style.setProperty('--text-primary', tp.text_color);
    }
}
// WebSocket: connect to API origin
const socket = io(API_BASE || window.location.origin, { path: '/socket.io' });
let monitoringEnabled = false;
let giftsCount = 0;

// Элементы DOM
const monitoringToggle = document.getElementById('monitoringToggle');
const monitoringToggleBtn = document.getElementById('monitoringToggleBtn');
const monitoringStatus = document.getElementById('monitoringStatus');
const monitoringBtnText = monitoringToggleBtn ? monitoringToggleBtn.querySelector('.monitoring-btn-text') : null;
const giftsGrid = document.getElementById('giftsGrid');
const giftsCountEl = document.getElementById('giftsCount');
const clearFiltersBtn = document.getElementById('clearFilters');
const seenGiftKeys = new Set();
const collectionsTagsEl = document.getElementById('collectionsTags');
const modelsTagsEl = document.getElementById('modelsTags');
const selectCollectionsBtn = document.getElementById('selectCollections');
const selectModelsBtn = document.getElementById('selectModels');
const minPriceEl = document.getElementById('minPrice');
const maxPriceEl = document.getElementById('maxPrice');
const minPriceValueEl = document.getElementById('minPriceValue');
const maxPriceValueEl = document.getElementById('maxPriceValue');
const rangeTrackActiveEl = document.getElementById('rangeTrackActive');

// Фильтры панель
const filtersPanel = document.getElementById('filtersPanel');
const closeFilters = document.getElementById('closeFilters');
let activeFilterType = null;
let filtersPanelCloseTimer = null;

// Individual filter buttons
const filterButtons = {
    marketplaces: document.getElementById('filterMarketplaces'),
    collections: document.getElementById('filterCollections'),
    models: document.getElementById('filterModels'),
    backgrounds: document.getElementById('filterBackgrounds'),
    sort: document.getElementById('filterSort')
};

// Filter groups mapping
const filterGroups = {
    marketplaces: document.querySelector('[data-filter-group="marketplaces"]'),
    collections: document.querySelector('[data-filter-group="collections"]'),
    models: document.querySelector('[data-filter-group="models"]'),
    backgrounds: document.querySelector('[data-filter-group="backgrounds"]'),
    sort: document.querySelector('[data-filter-group="sort"]')
};

function positionFilterPanel(anchorEl) {
    if (!filtersPanel || !anchorEl) return;
    const rect = anchorEl.getBoundingClientRect();
    const panelWidth = filtersPanel.offsetWidth || 480;
    const margin = 16;
    const desiredCenter = rect.left + rect.width / 2;
    const minCenter = panelWidth / 2 + margin;
    const maxCenter = window.innerWidth - panelWidth / 2 - margin;
    const clampedCenter = Math.max(minCenter, Math.min(maxCenter, desiredCenter));
    const top = rect.bottom + 12;

    filtersPanel.style.setProperty('--filters-panel-left', `${clampedCenter}px`);
    filtersPanel.style.setProperty('--filters-panel-top', `${top}px`);
}

function openFilterPanel(filterType, anchorEl) {
    if (!filtersPanel) return;
    positionFilterPanel(anchorEl);

    Object.values(filterGroups).forEach(group => {
        if (group) group.style.display = 'none';
    });
    if (filterGroups[filterType]) {
        filterGroups[filterType].style.display = 'flex';
    }

    Object.values(filterButtons).forEach(btn => {
        if (btn) btn.classList.remove('active');
    });
    if (filterButtons[filterType]) {
        filterButtons[filterType].classList.add('active');
    }

    activeFilterType = filterType;
    if (filtersPanelCloseTimer) {
        clearTimeout(filtersPanelCloseTimer);
        filtersPanelCloseTimer = null;
    }
    filtersPanel.classList.remove('closing');
    filtersPanel.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeFilterPanel() {
    if (filtersPanel) {
        filtersPanel.classList.add('closing');
        if (filtersPanelCloseTimer) {
            clearTimeout(filtersPanelCloseTimer);
        }
        filtersPanelCloseTimer = setTimeout(() => {
            filtersPanel.classList.remove('active', 'closing');
            document.body.style.overflow = '';
            activeFilterType = null;
            Object.values(filterButtons).forEach(btn => {
                if (btn) btn.classList.remove('active');
            });
            filtersPanelCloseTimer = null;
        }, 320);
    }
}

Object.entries(filterButtons).forEach(([type, btn]) => {
    if (btn) {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (activeFilterType === type && filtersPanel.classList.contains('active')) {
                closeFilterPanel();
            } else {
                openFilterPanel(type, btn);
            }
        });
    }
});

if (closeFilters && filtersPanel) {
    closeFilters.addEventListener('click', (e) => {
        e.stopPropagation();
        closeFilterPanel();
    });
}

if (filtersPanel) {
    filtersPanel.addEventListener('click', (e) => {
        if (e.target === filtersPanel || e.target.classList.contains('filters-panel')) {
            closeFilterPanel();
        }
    });
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (filtersPanel && filtersPanel.classList.contains('active')) {
            closeFilterPanel();
        }
        if (giftModal && !giftModal.classList.contains('hidden')) {
            closeGiftModal();
        }
    }
});

let selectedCollections = [];
let selectedModels = [];
const PRICE_MAX = 10000;
let catalogCache = null;

async function loadStatus() {
    try {
        const response = await fetch(API_BASE + '/api/status', { headers: apiHeaders() });
        const data = await response.json();
        monitoringEnabled = data.enabled;
        monitoringToggle.checked = monitoringEnabled;
        updateMonitoringStatus();
        updateFilters(data.filters);
    } catch (error) {
        console.error('Error loading status:', error);
    }
}

function updateMonitoringStatus() {
    if (monitoringToggleBtn) {
        const icon = monitoringToggleBtn.querySelector('.material-symbols-outlined');
        if (icon) {
            icon.textContent = monitoringEnabled ? 'pause_circle' : 'play_circle';
        }
        monitoringToggleBtn.classList.toggle('active', monitoringEnabled);
        if (monitoringBtnText) {
            monitoringBtnText.textContent = monitoringEnabled ? 'Мониторинг включен' : 'Мониторинг';
        }
    }
    if (monitoringStatus) {
        if (monitoringEnabled) {
            monitoringStatus.textContent = 'Мониторинг включен';
            monitoringStatus.style.color = '#ffffff';
        } else {
            monitoringStatus.textContent = 'Мониторинг выключен';
            monitoringStatus.style.color = 'rgba(255, 255, 255, 0.5)';
        }
    }
}

if (monitoringToggleBtn && monitoringToggle) {
    monitoringToggle.classList.remove('pristine');
    monitoringToggleBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const enabled = !monitoringToggle.checked;
        monitoringToggle.checked = enabled;
        monitoringToggle.classList.remove('pristine');
        await toggleMonitoring(enabled);
    });
}

async function toggleMonitoring(enabled) {
    monitoringEnabled = enabled;
    monitoringToggle.checked = enabled;
    updateMonitoringStatus();

    if (!enabled) {
        giftsGrid.innerHTML = '<div class="empty-state"><span class="material-symbols-outlined">inbox</span><p>Мониторинг выключен</p></div>';
        giftsCount = 0;
        updateGiftsCount();
        seenGiftKeys.clear();
    }

    try {
        const response = await fetch(API_BASE + '/api/toggle', {
            method: 'POST',
            headers: apiHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ enabled })
        });
        const data = await response.json();
        if (data.enabled !== monitoringEnabled) {
            monitoringEnabled = data.enabled;
            monitoringToggle.checked = monitoringEnabled;
            updateMonitoringStatus();
        }
    } catch (error) {
        console.error('Error toggling monitoring:', error);
        monitoringEnabled = !enabled;
        monitoringToggle.checked = !enabled;
        updateMonitoringStatus();
    }
}

monitoringToggle.addEventListener('change', async (e) => {
    await toggleMonitoring(e.target.checked);
});

let applyFiltersTimer = null;
let suppressAutoApply = false;

async function applyFiltersImmediate() {
    const filters = getFilters();
    try {
        const response = await fetch(API_BASE + '/api/filters', {
            method: 'POST',
            headers: apiHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(filters)
        });
        if (response.ok) {
            giftsGrid.innerHTML = '<div class="empty-state"><span class="material-symbols-outlined">inbox</span><p>Фильтры применены. Ожидание новых подарков...</p></div>';
            giftsCount = 0;
            updateGiftsCount();
        }
    } catch (error) {
        console.error('Error applying filters:', error);
    }
}

function scheduleApplyFilters() {
    if (suppressAutoApply) return;
    if (applyFiltersTimer) clearTimeout(applyFiltersTimer);
    applyFiltersTimer = setTimeout(() => applyFiltersImmediate(), 250);
}

clearFiltersBtn.addEventListener('click', () => {
    selectedCollections = [];
    selectedModels = [];
    renderSelectedTags();
    document.getElementById('backgrounds').value = '';
    minPriceEl.value = 0;
    maxPriceEl.value = PRICE_MAX;
    updatePriceLabels();
    document.getElementById('sort').value = 'latest';
    document.querySelectorAll('.marketplace-checkbox').forEach(cb => { cb.checked = true; });
    applyFiltersImmediate();
});

document.querySelectorAll('.marketplace-checkbox').forEach(cb => {
    cb.addEventListener('change', scheduleApplyFilters);
});
const backgroundsInput = document.getElementById('backgrounds');
if (backgroundsInput) backgroundsInput.addEventListener('input', scheduleApplyFilters);
const sortSelect = document.getElementById('sort');
if (sortSelect) sortSelect.addEventListener('change', scheduleApplyFilters);

function splitListInput(id) {
    return document.getElementById(id).value.split(',').map(v => v.trim()).filter(v => v.length > 0);
}

function getFilters() {
    const marketplaces = Array.from(document.querySelectorAll('.marketplace-checkbox:checked')).map(cb => cb.value);
    return {
        marketplaces,
        collections: selectedCollections,
        models: selectedModels,
        backgrounds: splitListInput('backgrounds'),
        min_price: minPriceEl.value || null,
        max_price: maxPriceEl.value || null,
        sort: document.getElementById('sort').value
    };
}

function updateFilters(filters) {
    suppressAutoApply = true;
    if (filters.marketplaces) {
        document.querySelectorAll('.marketplace-checkbox').forEach(cb => {
            cb.checked = filters.marketplaces.includes(cb.value);
        });
    }
    if (filters.collections) selectedCollections = filters.collections;
    if (filters.models) selectedModels = filters.models;
    if (filters.backgrounds) document.getElementById('backgrounds').value = filters.backgrounds.join(', ');
    if (filters.min_price !== undefined && filters.min_price !== null) minPriceEl.value = filters.min_price;
    if (filters.max_price !== undefined && filters.max_price !== null) maxPriceEl.value = filters.max_price;
    if (filters.sort) document.getElementById('sort').value = filters.sort;
    renderSelectedTags();
    updatePriceLabels();
    suppressAutoApply = false;
}

function addGift(gift) {
    const giftKey = getGiftKey(gift);
    if (seenGiftKeys.has(giftKey)) return;
    seenGiftKeys.add(giftKey);

    const emptyState = giftsGrid.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const card = document.createElement('div');
    card.className = 'gift-card';
    const bg = document.createElement('div');
    bg.className = 'bg';
    bg.style.backgroundImage = `url(${gift.photo_url || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="280" height="280"%3E%3Crect fill="%23252525" width="280" height="280"/%3E%3Ctext x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%23666" font-family="Arial" font-size="14"%3EНет изображения%3C/text%3E%3C/svg%3E'})`;
    const blur = document.createElement('div');
    blur.className = 'blur';
    blur.style.backgroundImage = `url(${gift.photo_url || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="280" height="280"%3E%3Crect fill="%23252525" width="280" height="280"/%3E%3Ctext x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%23666" font-family="Arial" font-size="14"%3EНет изображения%3C/text%3E%3C/svg%3E'})`;
    card.appendChild(bg);
    card.appendChild(blur);

    const imageWrapper = document.createElement('div');
    imageWrapper.className = 'gift-image-wrapper';
    const image = document.createElement('img');
    image.className = 'gift-image';
    image.src = gift.photo_url || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="280" height="280"%3E%3Crect fill="%23252525" width="280" height="280"/%3E%3Ctext x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%23666" font-family="Arial" font-size="14"%3EНет изображения%3C/text%3E%3C/svg%3E';
    image.alt = gift.name;
    image.onerror = function() {
        this.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="280" height="280"%3E%3Crect fill="%23252525" width="280" height="280"/%3E%3Ctext x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%23666" font-family="Arial" font-size="14"%3EОшибка загрузки%3C/text%3E%3C/svg%3E';
        bg.style.backgroundImage = `url(${this.src})`;
        blur.style.backgroundImage = `url(${this.src})`;
    };
    imageWrapper.appendChild(image);

    const info = document.createElement('div');
    info.className = 'gift-info';
    const name = document.createElement('div');
    name.className = 'gift-name';
    name.textContent = gift.name;
    const model = document.createElement('div');
    model.className = 'gift-model';
    model.textContent = gift.model;
    const price = document.createElement('div');
    price.className = 'gift-price';
    price.textContent = `${gift.price} TON`;
    const floor = document.createElement('div');
    floor.className = 'gift-floor';
    floor.textContent = `Флор подарка: ${formatFloor(gift.floor_price)}`;
    const modelFloor = document.createElement('div');
    modelFloor.className = 'gift-model-floor';
    modelFloor.textContent = `Флор модели: ${formatFloor(gift.model_floor_price)}`;

    const marketplace = document.createElement('a');
    marketplace.className = 'gift-marketplace';
    marketplace.textContent = gift.marketplace.toUpperCase();
    marketplace.href = '#';
    marketplace.onclick = async (e) => {
        e.stopPropagation();
        try {
            const response = await fetch(API_BASE + '/api/gift_details', {
                method: 'POST',
                headers: apiHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(gift),
            });
            const data = await response.json();
            if (data.marketplace_link && data.marketplace_link !== '#') {
                if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.openLink) {
                    window.Telegram.WebApp.openLink(data.marketplace_link);
                } else {
                    window.open(data.marketplace_link, '_blank');
                }
            }
        } catch (err) {
            console.error('Error getting marketplace link:', err);
        }
        return false;
    };

    info.appendChild(name);
    info.appendChild(model);
    info.appendChild(price);
    info.appendChild(floor);
    info.appendChild(modelFloor);
    info.appendChild(marketplace);
    card.appendChild(imageWrapper);
    card.appendChild(info);

    card.addEventListener('click', () => openGiftModal(gift));

    giftsGrid.insertBefore(card, giftsGrid.firstChild);
    giftsCount++;
    updateGiftsCount();

    const cards = giftsGrid.querySelectorAll('.gift-card');
    if (cards.length > 100) {
        cards[cards.length - 1].remove();
        giftsCount--;
        updateGiftsCount();
    }

    card.style.opacity = '0';
    card.style.transform = 'translateY(-50px) scale(0.8)';
    card.style.filter = 'blur(20px)';
    const allCards = giftsGrid.querySelectorAll('.gift-card');
    const delay = Math.min(Array.from(allCards).indexOf(card) * 60, 400);
    setTimeout(() => {
        card.style.transition = 'all 0.5s ease';
        card.style.opacity = '1';
        card.style.transform = '';
        card.style.filter = 'blur(0)';
    }, 10 + delay);
}

function updateGiftsCount() {
    giftsCountEl.textContent = `${giftsCount} подарков`;
}

function formatFloor(value) {
    if (value === null || value === undefined || value === '' || Number.isNaN(value)) return 'N/A';
    const num = Number(value);
    if (Number.isNaN(num) || num <= 0) return 'N/A';
    return `${num.toFixed(2)} TON`;
}

function getGiftKey(gift) {
    if (gift && gift.id) return String(gift.id);
    return [gift?.marketplace || 'unknown', gift?.name || 'unknown', gift?.model || 'unknown', gift?.gift_number || gift?.timestamp || 'unknown'].join('|');
}

let giftModal = null;
let giftModalCloseTimer = null;

function ensureGiftModal() {
    if (giftModal) return;
    giftModal = document.createElement('div');
    giftModal.className = 'gift-modal hidden';
    giftModal.innerHTML = `
        <div class="gift-modal-backdrop"></div>
        <div class="gift-modal-content">
            <button class="gift-modal-close" type="button"><span class="material-symbols-outlined">close</span></button>
            <div class="gift-modal-header"><h3 id="giftModalTitle">Подарок</h3></div>
            <div id="giftModalDetails" class="gift-modal-details"></div>
            <div class="gift-modal-sales">
                <div>
                    <a id="giftModalSalesLink" class="gift-modal-sales-link" href="#" target="_blank" rel="noreferrer">
                        <span class="material-symbols-outlined">open_in_new</span> Последние продажи модели (Tonnel)
                    </a>
                    <ul id="giftModalModelSales"></ul>
                </div>
            </div>
            <div class="gift-modal-footer">
                <a id="giftModalLink" class="gift-modal-marketplace-btn" href="#" target="_blank" rel="noreferrer">
                    <span class="material-symbols-outlined">store</span>
                    <span id="giftModalMarketplaceName">МАРКЕТПЛЕЙС</span>
                </a>
            </div>
        </div>
    `;
    document.body.appendChild(giftModal);
    giftModal.querySelector('.gift-modal-backdrop').addEventListener('click', closeGiftModal);
    giftModal.querySelector('.gift-modal-close').addEventListener('click', closeGiftModal);
}

function openGiftModal(gift) {
    ensureGiftModal();
    const titleEl = document.getElementById('giftModalTitle');
    const linkEl = document.getElementById('giftModalLink');
    const marketplaceNameEl = document.getElementById('giftModalMarketplaceName');
    const salesLinkEl = document.getElementById('giftModalSalesLink');
    const detailsEl = document.getElementById('giftModalDetails');
    const modelSalesEl = document.getElementById('giftModalModelSales');

    titleEl.textContent = `${gift.name} — ${gift.model}`;
    linkEl.href = '#';
    linkEl.classList.add('disabled');
    salesLinkEl.href = '#';
    salesLinkEl.classList.add('disabled');
    marketplaceNameEl.textContent = gift.marketplace.toUpperCase();

    detailsEl.innerHTML = `
        <div><strong>Маркет:</strong> ${gift.marketplace.toUpperCase()}</div>
        <div><strong>Цена:</strong> ${formatFloor(gift.price)}</div>
        <div><strong>Флор подарка:</strong> ${formatFloor(gift.floor_price)}</div>
        <div><strong>Флор модели:</strong> ${formatFloor(gift.model_floor_price)}</div>
        <div><strong>Номер:</strong> ${gift.gift_number || 'N/A'}</div>
        <div><strong>Время:</strong> ${formatTimestamp(gift.timestamp)}</div>
    `;
    modelSalesEl.innerHTML = '<li>Загрузка...</li>';
    if (giftModalCloseTimer) {
        clearTimeout(giftModalCloseTimer);
        giftModalCloseTimer = null;
    }
    giftModal.classList.remove('hidden', 'closing');

    fetch(API_BASE + '/api/gift_details', {
        method: 'POST',
        headers: apiHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(gift),
    })
        .then(res => res.json())
        .then(data => {
            if (data.marketplace_link && data.marketplace_link !== '#') {
                linkEl.href = data.marketplace_link;
                linkEl.classList.remove('disabled');
                salesLinkEl.href = data.marketplace_link;
                salesLinkEl.classList.remove('disabled');
            }
            renderSalesList(modelSalesEl, data.model_sales, gift.name);
        })
        .catch(() => { modelSalesEl.innerHTML = '<li>Нет данных</li>'; });
}

function closeGiftModal() {
    if (giftModal) {
        giftModal.classList.add('closing');
        if (giftModalCloseTimer) clearTimeout(giftModalCloseTimer);
        giftModalCloseTimer = setTimeout(() => {
            giftModal.classList.add('hidden');
            giftModal.classList.remove('closing');
            giftModalCloseTimer = null;
        }, 350);
    }
}

function renderSalesList(container, sales, giftName) {
    if (!Array.isArray(sales) || sales.length === 0) {
        container.innerHTML = '<li>Нет данных</li>';
        return;
    }
    container.innerHTML = '';
    sales.forEach(sale => {
        const price = sale.price ?? sale.amount ?? sale.value ?? 'N/A';
        const model = sale.model || sale.model_name || '';
        const time = sale.time || sale.created_at || sale.timestamp || sale.date || '';
        const saleNumber = sale.gift_num || sale.gift_number || sale.number || sale.external_collection_number || null;
        const item = document.createElement('li');
        const parts = [];
        if (price !== 'N/A') parts.push(`${price} TON`);
        if (model) {
            const modelEl = document.createElement('a');
            modelEl.className = 'gift-modal-sale-link';
            modelEl.textContent = model;
            const nftLink = buildNftLink(giftName, saleNumber);
            if (nftLink) {
                modelEl.href = nftLink;
                modelEl.target = '_blank';
                modelEl.rel = 'noreferrer';
            } else {
                modelEl.href = '#';
                modelEl.classList.add('disabled');
            }
            parts.push(modelEl);
        }
        if (time) parts.push(formatTimestamp(time));
        if (parts.length === 0) item.textContent = 'Продажа';
        else {
            parts.forEach((part, idx) => {
                if (idx > 0) item.appendChild(document.createTextNode(' · '));
                if (part instanceof Node) item.appendChild(part);
                else item.appendChild(document.createTextNode(String(part)));
            });
        }
        container.appendChild(item);
    });
}

function buildNftLink(name, number) {
    if (!name || !number) return null;
    const slug = String(name).toLowerCase().replace(/[^a-z0-9]/g, '');
    if (!slug) return null;
    return `https://t.me/nft/${slug}-${number}`;
}

function formatTimestamp(value) {
    if (!value) return 'N/A';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
}

function updatePriceLabels() {
    minPriceEl.max = PRICE_MAX;
    maxPriceEl.max = PRICE_MAX;
    if (Number(minPriceEl.value) > Number(maxPriceEl.value)) {
        const temp = minPriceEl.value;
        minPriceEl.value = maxPriceEl.value;
        maxPriceEl.value = temp;
    }
    minPriceValueEl.textContent = minPriceEl.value;
    maxPriceValueEl.textContent = maxPriceEl.value;
    const minPercent = (Number(minPriceEl.value) / PRICE_MAX) * 100;
    const maxPercent = (Number(maxPriceEl.value) / PRICE_MAX) * 100;
    if (rangeTrackActiveEl) {
        rangeTrackActiveEl.style.left = `${minPercent}%`;
        rangeTrackActiveEl.style.width = `${Math.max(maxPercent - minPercent, 0)}%`;
    }
}

minPriceEl.addEventListener('input', () => { updatePriceLabels(); scheduleApplyFilters(); });
maxPriceEl.addEventListener('input', () => { updatePriceLabels(); scheduleApplyFilters(); });

selectCollectionsBtn.addEventListener('click', () => openSelector('collection'));
selectModelsBtn.addEventListener('click', () => openSelector('model'));

function renderSelectedTags() {
    renderTags(collectionsTagsEl, selectedCollections);
    renderTags(modelsTagsEl, selectedModels);
    document.getElementById('collections').value = selectedCollections.join(', ');
    document.getElementById('models').value = selectedModels.join(', ');
    updateFilterCounts();
    if (!suppressAutoApply) scheduleApplyFilters();
}

function updateFilterCounts() {
    const collectionsCountEl = document.getElementById('collectionsCount');
    const modelsCountEl = document.getElementById('modelsCount');
    if (collectionsCountEl) {
        const count = selectedCollections.length;
        collectionsCountEl.textContent = String(count);
        collectionsCountEl.classList.toggle('is-visible', count > 0);
    }
    if (modelsCountEl) {
        const count = selectedModels.length;
        modelsCountEl.textContent = String(count);
        modelsCountEl.classList.toggle('is-visible', count > 0);
    }
}

function renderTags(container, items) {
    container.innerHTML = '';
    if (!items.length) {
        container.innerHTML = '<span class="chip-placeholder">Не выбрано</span>';
        return;
    }
    items.forEach(item => {
        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.textContent = item;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'chip-remove';
        remove.textContent = '×';
        remove.addEventListener('click', () => {
            if (container === collectionsTagsEl) selectedCollections = selectedCollections.filter(c => c !== item);
            else selectedModels = selectedModels.filter(m => m !== item);
            renderSelectedTags();
        });
        chip.appendChild(remove);
        container.appendChild(chip);
    });
}

async function openSelector(type) {
    ensureSelectorModal();
    const modal = document.getElementById('selectorModal');
    const title = document.getElementById('selectorTitle');
    const list = document.getElementById('selectorList');
    const search = document.getElementById('selectorSearch');
    const emptyState = document.getElementById('selectorEmptyState');

    title.textContent = type === 'collection' ? 'Коллекции' : 'Модели';
    search.value = '';
    list.innerHTML = '<li>Загрузка...</li>';
    if (emptyState) emptyState.classList.add('hidden');
    modal.dataset.type = type;

    if (!catalogCache) {
        try {
            const response = await fetch(API_BASE + '/api/catalog', { headers: apiHeaders() });
            catalogCache = response.ok ? await response.json() : null;
        } catch (e) {
            catalogCache = null;
        }
    }

    let items = [];
    if (catalogCache) {
        if (type === 'collection') {
            items = (catalogCache.collections || []).map(name => ({ name }));
        } else {
            const modelsByCollection = catalogCache.models_by_collection || {};
            const collections = selectedCollections.length ? selectedCollections : Object.keys(modelsByCollection);
            const modelsSet = new Set();
            collections.forEach(collection => {
                (modelsByCollection[collection] || []).forEach(model => modelsSet.add(model));
            });
            items = Array.from(modelsSet).sort().map(name => ({ name }));
        }
    }
    renderSelectorList(items, type);
    if (items.length === 0 && emptyState) {
        emptyState.classList.remove('hidden');
        emptyState.querySelector('.selector-empty-text').textContent = type === 'collection'
            ? 'Коллекций пока нет. Каталог загружается с маркетплейсов на сервере.'
            : 'Моделей пока нет. Сначала выберите коллекции или обновите каталог.';
    }
    modal.classList.remove('hidden');
}

async function refreshCatalogFromSelector() {
    const modal = document.getElementById('selectorModal');
    const list = document.getElementById('selectorList');
    const btn = document.getElementById('selectorRefreshCatalog');
    const type = modal && modal.dataset.type;
    if (!type) return;
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Загрузка...';
    }
    list.innerHTML = '<li>Запуск построения каталога на сервере...</li>';
    try {
        await fetch(API_BASE + '/api/catalog/build', { method: 'POST', headers: apiHeaders() });
        await new Promise(r => setTimeout(r, 4000));
    } catch (e) {}
    catalogCache = null;
    try {
        const response = await fetch(API_BASE + '/api/catalog', { headers: apiHeaders() });
        catalogCache = response.ok ? await response.json() : null;
    } catch (e) {
        catalogCache = null;
    }
    if (btn) {
        btn.disabled = false;
        btn.textContent = 'Обновить каталог';
    }
    let items = [];
    if (catalogCache) {
        if (type === 'collection') {
            items = (catalogCache.collections || []).map(name => ({ name }));
        } else {
            const modelsByCollection = catalogCache.models_by_collection || {};
            const collections = selectedCollections.length ? selectedCollections : Object.keys(modelsByCollection);
            const modelsSet = new Set();
            collections.forEach(collection => {
                (modelsByCollection[collection] || []).forEach(model => modelsSet.add(model));
            });
            items = Array.from(modelsSet).sort().map(name => ({ name }));
        }
    }
    renderSelectorList(items, type);
    const emptyState = document.getElementById('selectorEmptyState');
    if (items.length === 0 && emptyState) emptyState.classList.remove('hidden');
    else if (emptyState) emptyState.classList.add('hidden');
}

function ensureSelectorModal() {
    if (document.getElementById('selectorModal')) return;
    const modal = document.createElement('div');
    modal.id = 'selectorModal';
    modal.className = 'selector-modal hidden';
    modal.innerHTML = `
        <div class="selector-backdrop"></div>
        <div class="selector-content">
            <div class="selector-header">
                <h3 id="selectorTitle">Коллекции</h3>
                <input id="selectorSearch" type="text" placeholder="Поиск..." />
            </div>
            <ul id="selectorList" class="selector-list"></ul>
            <div id="selectorEmptyState" class="selector-empty-state hidden">
                <p class="selector-empty-text">Каталог пуст. Коллекции загружаются с маркетплейсов на сервере.</p>
                <p class="selector-empty-hint">Запустите GUI-сервер (<code>python gui/server.py</code>), подождите 1–2 минуты или нажмите «Обновить каталог».</p>
                <button id="selectorRefreshCatalog" type="button" class="btn btn-primary">Обновить каталог</button>
            </div>
            <div class="selector-actions">
                <button id="selectorCancel" type="button" class="btn btn-secondary">Закрыть</button>
                <button id="selectorApply" type="button" class="btn btn-primary">Применить</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    modal.querySelector('.selector-backdrop').addEventListener('click', closeSelector);
    modal.querySelector('#selectorCancel').addEventListener('click', closeSelector);
    modal.querySelector('#selectorApply').addEventListener('click', applySelector);
    modal.querySelector('#selectorSearch').addEventListener('input', () => {
        const t = modal.dataset.type;
        const items = JSON.parse(modal.dataset.items || '[]');
        const query = modal.querySelector('#selectorSearch').value.toLowerCase();
        renderSelectorList(items.filter(item => item.name.toLowerCase().includes(query)), t);
    });
    modal.querySelector('#selectorRefreshCatalog').addEventListener('click', refreshCatalogFromSelector);
}

function renderSelectorList(items, type) {
    const modal = document.getElementById('selectorModal');
    const list = document.getElementById('selectorList');
    modal.dataset.items = JSON.stringify(items);
    list.innerHTML = '';
    const selected = type === 'collection' ? selectedCollections : selectedModels;

    items.forEach(item => {
        const li = document.createElement('li');
        li.className = 'selector-item';
        const checked = selected.includes(item.name);
        let imageUrl = '';
        if (catalogCache) {
            if (type === 'collection') {
                const models = catalogCache.models_by_collection?.[item.name] || [];
                if (models.length > 0) {
                    const modelName = models[0];
                    imageUrl = catalogCache.model_images?.[modelName] || catalogCache.collection_images?.[item.name] || '';
                } else {
                    imageUrl = catalogCache.collection_images?.[item.name] || '';
                }
            } else {
                imageUrl = catalogCache.model_images?.[item.name] || '';
            }
        }
        const dataBase = API_BASE ? API_BASE : '';
        const imageHtml = imageUrl ? `<img src="${dataBase}/data/${imageUrl}" alt="${item.name}" class="selector-item-image" onerror="this.style.display='none'">` : '';
        li.innerHTML = `
            <label>
                <input type="checkbox" ${checked ? 'checked' : ''} data-name="${item.name}">
                ${imageHtml}
                <span class="selector-name">${item.name}</span>
            </label>
        `;
        list.appendChild(li);
    });
    if (!items.length) {
        list.innerHTML = '<li class="selector-empty">Нет данных</li>';
        const emptyState = document.getElementById('selectorEmptyState');
        if (emptyState) emptyState.classList.remove('hidden');
    } else {
        const emptyState = document.getElementById('selectorEmptyState');
        if (emptyState) emptyState.classList.add('hidden');
    }
}

function applySelector() {
    const modal = document.getElementById('selectorModal');
    const type = modal.dataset.type;
    const checks = Array.from(modal.querySelectorAll('input[type="checkbox"]'));
    const selected = checks.filter(c => c.checked).map(c => c.dataset.name);
    if (type === 'collection') selectedCollections = selected;
    else selectedModels = selected;
    renderSelectedTags();
    closeSelector();
}

function closeSelector() {
    const modal = document.getElementById('selectorModal');
    modal.classList.add('hidden');
}

async function pollRecentGifts() {
    try {
        const response = await fetch(API_BASE + '/api/gifts', { headers: apiHeaders() });
        if (!response.ok) return;
        const items = await response.json();
        if (Array.isArray(items)) items.forEach(addGift);
    } catch (error) {}
}

socket.on('connect', () => { console.log('Connected to server'); });
socket.on('disconnect', () => { console.log('Disconnected from server'); });
socket.on('status', (data) => {
    monitoringEnabled = data.enabled;
    monitoringToggle.checked = monitoringEnabled;
    updateMonitoringStatus();
});
socket.on('new_gift', (gift) => { addGift(gift); });

loadStatus();
pollRecentGifts();
setInterval(pollRecentGifts, 3000);
initBackgroundCanvas();

function initBackgroundCanvas() {
    const canvas = document.getElementById('bgCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const blobs = [
        { x: 0.2, y: 0.3, r: 0.35, vx: 0.0002, vy: 0.00015, color: 'rgba(91, 134, 229, 0.35)' },
        { x: 0.8, y: 0.2, r: 0.4, vx: -0.00015, vy: 0.00012, color: 'rgba(54, 209, 220, 0.3)' },
        { x: 0.6, y: 0.8, r: 0.5, vx: 0.0001, vy: -0.00018, color: 'rgba(124, 209, 127, 0.25)' },
    ];
    const resize = () => {
        const ratio = window.devicePixelRatio || 1;
        canvas.width = window.innerWidth * ratio;
        canvas.height = window.innerHeight * ratio;
        canvas.style.width = `${window.innerWidth}px`;
        canvas.style.height = `${window.innerHeight}px`;
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    const draw = () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.globalCompositeOperation = 'lighter';
        blobs.forEach(blob => {
            blob.x += blob.vx;
            blob.y += blob.vy;
            if (blob.x < 0.1 || blob.x > 0.9) blob.vx *= -1;
            if (blob.y < 0.1 || blob.y > 0.9) blob.vy *= -1;
            const x = blob.x * window.innerWidth;
            const y = blob.y * window.innerHeight;
            const radius = blob.r * Math.min(window.innerWidth, window.innerHeight);
            const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
            gradient.addColorStop(0, blob.color);
            gradient.addColorStop(1, 'rgba(12, 16, 28, 0)');
            ctx.fillStyle = gradient;
            ctx.beginPath();
            ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fill();
        });
        ctx.restore();
        requestAnimationFrame(draw);
    };
    resize();
    window.addEventListener('resize', resize);
    requestAnimationFrame(draw);
}
