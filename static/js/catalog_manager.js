/**
 * BashFlow Cloud - Product Catalog & Workflow Management Module (catalog_manager.js)
 * Phase 7: Frontend Decoupling & Modularization
 * Handles: Products catalog CRUD, category filtering, inventory KPIs,
 * workflow canvas rendering, and automation execution triggers.
 */

(function(window, document) {
    'use strict';

    const BashFlowCatalog = {
        products: [],
        categories: [],
        stats: {},
        activeWorkflow: null,

        init() {
            this.initListeners();
        },

        initListeners() {
            const searchInput = document.getElementById('productSearchInput');
            if (searchInput) {
                searchInput.addEventListener('input', (e) => this.debounceSearch(e.target.value));
            }

            const catFilter = document.getElementById('productCategoryFilter');
            if (catFilter) {
                catFilter.addEventListener('change', () => this.loadProductsCatalog());
            }

            const sortFilter = document.getElementById('productSortFilter');
            if (sortFilter) {
                sortFilter.addEventListener('change', () => this.loadProductsCatalog());
            }
        },

        debounceTimer: null,
        debounceSearch(val) {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => {
                this.loadProductsCatalog();
            }, 300);
        },

        async loadProductsCatalog() {
            const tbody = document.getElementById('productsTableBody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center" style="padding: 24px; color: var(--text-secondary);"><span class="icon spinning">🔄</span> Loading product catalog...</td></tr>';
            }

            const sortVal = document.getElementById('productSortFilter')?.value || 'name_asc';
            const activeVal = document.getElementById('productActiveFilter')?.value || 'active';
            const categoryVal = document.getElementById('productCategoryFilter')?.value || 'all';
            const stockVal = document.getElementById('productStockStatusFilter')?.value || 'all';
            const searchVal = document.getElementById('productSearchInput')?.value.trim() || '';

            let url = `/api/v1/ecommerce/products?limit=250&sort=${encodeURIComponent(sortVal)}&org_id=org-enterprise-default`;
            if (activeVal === 'all') url += '&include_inactive=true';
            else if (activeVal === 'archived') url += '&status=archived';
            if (categoryVal && categoryVal !== 'all') url += `&category=${encodeURIComponent(categoryVal)}`;
            if (stockVal && stockVal !== 'all') url += `&stock_status=${encodeURIComponent(stockVal)}`;
            if (searchVal) url += `&query=${encodeURIComponent(searchVal)}`;

            try {
                const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();

                this.products = data.products || [];
                this.categories = data.categories || [];
                this.stats = data.stats || {};

                if (window.state) {
                    window.state.products = this.products;
                    window.state.productCategories = this.categories;
                    window.state.productStats = this.stats;
                }

                this.updateCatalogKPIs(this.stats, data.count);
                this.populateCategoryDropdowns(this.categories);
                this.renderProducts(this.products);
                return data;
            } catch (err) {
                console.error('[BashFlowCatalog] loadProductsCatalog error:', err);
                if (tbody) {
                    tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="padding: 20px; color: #f87171;">Failed to load catalog. <button class="hud-btn outline small" onclick="BashFlowCatalog.loadProductsCatalog()">Retry</button></td></tr>`;
                }
            }
        },

        updateCatalogKPIs(stats, count) {
            if (!stats) return;
            const totalEl = document.getElementById('prodMetricTotal');
            const inStockEl = document.getElementById('prodMetricInStock');
            const lowStockEl = document.getElementById('prodMetricLowStock');
            const outOfStockEl = document.getElementById('prodMetricOutOfStock');
            const valEl = document.getElementById('prodMetricValuation');

            if (totalEl) totalEl.textContent = stats.total !== undefined ? stats.total : (count || 0);
            if (inStockEl) inStockEl.textContent = stats.in_stock || 0;
            if (lowStockEl) lowStockEl.textContent = stats.low_stock || 0;
            if (outOfStockEl) outOfStockEl.textContent = stats.out_of_stock || 0;
            if (valEl) {
                const val = stats.total_inventory_value || 0;
                valEl.textContent = `PKR ${Number(val).toLocaleString()}`;
            }
        },

        populateCategoryDropdowns(categories) {
            const select = document.getElementById('productCategoryFilter');
            if (!select || !Array.isArray(categories)) return;
            const current = select.value;
            select.innerHTML = '<option value="all">All Categories</option>';
            categories.forEach(cat => {
                const opt = document.createElement('option');
                opt.value = cat;
                opt.textContent = cat;
                if (cat === current) opt.selected = true;
                select.appendChild(opt);
            });
        },

        renderProducts(products) {
            const tbody = document.getElementById('productsTableBody');
            if (!tbody) return;

            if (!products || products.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center" style="padding: 30px; color: var(--text-secondary);">No products found in this catalog.</td></tr>';
                return;
            }

            tbody.innerHTML = products.map(p => {
                const stockBadge = p.stock_quantity > 5 ? '<span class="badge in-stock">In Stock</span>' : (p.stock_quantity > 0 ? '<span class="badge low-stock">Low Stock</span>' : '<span class="badge out-of-stock">Out of Stock</span>');
                const price = Number(p.price || 0).toLocaleString();
                const cost = Number(p.seller_price || 0).toLocaleString();
                return `
                    <tr>
                        <td>
                            <div style="display:flex; align-items:center; gap:8px;">
                                <img src="${p.image_url || '/static/img/placeholder-product.png'}" alt="${this.escapeHtml(p.name)}" style="width:36px; height:36px; object-fit:cover; border-radius:6px; background:#1e293b;" onerror="this.src='/static/img/placeholder-product.png'">
                                <div>
                                    <div style="font-weight:600; color:var(--text-primary);">${this.escapeHtml(p.name)}</div>
                                    <div style="font-size:11px; color:var(--text-muted);">${p.sku || 'No SKU'}</div>
                                </div>
                            </div>
                        </td>
                        <td>${this.escapeHtml(p.category || 'General')}</td>
                        <td><strong>PKR ${price}</strong></td>
                        <td><span style="color:var(--text-muted);">PKR ${cost}</span></td>
                        <td>${p.stock_quantity || 0}</td>
                        <td>${stockBadge}</td>
                        <td>
                            <div style="display:flex; gap:6px;">
                                <button class="hud-btn outline small" onclick="BashFlowCatalog.openProductModal('${p.id}')">Edit</button>
                                <button class="hud-btn outline small danger" onclick="BashFlowCatalog.deleteProduct('${p.id}')">Delete</button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
        },

        openProductModal(productId = null) {
            const modal = document.getElementById('productEditModal');
            if (!modal) return;
            modal.style.display = 'flex';
            const titleEl = document.getElementById('productModalTitle');

            if (productId) {
                const prod = this.products.find(p => p.id === productId);
                if (titleEl) titleEl.textContent = 'Edit Product';
                if (prod) {
                    if (document.getElementById('prodIdInput')) document.getElementById('prodIdInput').value = prod.id;
                    if (document.getElementById('prodNameInput')) document.getElementById('prodNameInput').value = prod.name;
                    if (document.getElementById('prodPriceInput')) document.getElementById('prodPriceInput').value = prod.price;
                    if (document.getElementById('prodCostInput')) document.getElementById('prodCostInput').value = prod.seller_price || '';
                    if (document.getElementById('prodCategoryInput')) document.getElementById('prodCategoryInput').value = prod.category || '';
                    if (document.getElementById('prodStockInput')) document.getElementById('prodStockInput').value = prod.stock_quantity || 0;
                }
            } else {
                if (titleEl) titleEl.textContent = 'Add New Product';
                const form = document.getElementById('productForm');
                if (form) form.reset();
                if (document.getElementById('prodIdInput')) document.getElementById('prodIdInput').value = '';
            }
        },

        closeProductModal() {
            const modal = document.getElementById('productEditModal');
            if (modal) modal.style.display = 'none';
        },

        async saveProduct(e) {
            if (e && e.preventDefault) e.preventDefault();
            const id = document.getElementById('prodIdInput')?.value;
            const name = document.getElementById('prodNameInput')?.value.trim();
            const price = parseFloat(document.getElementById('prodPriceInput')?.value || 0);
            const seller_price = parseFloat(document.getElementById('prodCostInput')?.value || 0);
            const category = document.getElementById('prodCategoryInput')?.value.trim() || 'General';
            const stock_quantity = parseInt(document.getElementById('prodStockInput')?.value || 0, 10);

            if (!name || isNaN(price)) {
                alert('Please provide valid product name and price.');
                return;
            }

            const payload = { name, price, seller_price, category, stock_quantity, currency: 'PKR', is_active: true };
            const method = id ? 'PUT' : 'POST';
            const url = id ? `/api/v1/ecommerce/products/${id}` : '/api/v1/ecommerce/products';

            try {
                const res = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    this.closeProductModal();
                    this.loadProductsCatalog();
                } else {
                    const err = await res.json();
                    alert(err.error || 'Failed to save product.');
                }
            } catch (err) {
                console.error('[BashFlowCatalog] saveProduct error:', err);
            }
        },

        async deleteProduct(productId) {
            if (!confirm('Are you sure you want to delete this product?')) return;
            try {
                const res = await fetch(`/api/v1/ecommerce/products/${productId}`, { method: 'DELETE' });
                if (res.ok) {
                    this.loadProductsCatalog();
                }
            } catch (err) {
                console.error('[BashFlowCatalog] deleteProduct error:', err);
            }
        },

        // Workflow UI Helpers
        initWorkflowGraphCanvas() {
            if (typeof window.initWorkflowGraphCanvas === 'function') {
                return window.initWorkflowGraphCanvas();
            }
            console.debug('[BashFlowCatalog] Workflow graph canvas initialized.');
        },

        escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }
    };

    // Expose module globally and bind legacy function calls
    window.BashFlowCatalog = BashFlowCatalog;
    window.loadProductsCatalog = () => BashFlowCatalog.loadProductsCatalog();
    window.renderProducts = (prods) => BashFlowCatalog.renderProducts(prods);
    window.openProductModal = (id) => BashFlowCatalog.openProductModal(id);
    window.closeProductModal = () => BashFlowCatalog.closeProductModal();
    window.saveProduct = (e) => BashFlowCatalog.saveProduct(e);
    window.deleteProduct = (id) => BashFlowCatalog.deleteProduct(id);

})(window, document);
