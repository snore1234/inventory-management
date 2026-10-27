<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget') }}</h3>
          <span class="budget-amount">{{ money(budget) }}</span>
        </div>
        <div class="budget-body">
          <input
            v-model.number="budget"
            type="range"
            class="budget-slider"
            min="0"
            :max="maxBudget"
            :step="sliderStep"
            :disabled="maxBudget === 0"
            :aria-label="t('restocking.budget')"
          />
          <div class="budget-scale">
            <span>{{ money(0) }}</span>
            <span>{{ t('restocking.budgetMax', { amount: money(maxBudget) }) }}</span>
          </div>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.itemsToOrder') }}</div>
          <div class="stat-value">{{ recommendations.length }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.totalSpend') }}</div>
          <div class="stat-value">{{ money(totalSpend) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ money(remainingBudget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.leadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: orderLeadTime }) }}</div>
        </div>
      </div>

      <div v-if="placedOrder" class="confirmation" role="status">
        <div>
          <strong>{{ t('restocking.orderPlaced', { orderNumber: placedOrder.order_number }) }}</strong>
          <p>{{ t('restocking.orderPlacedDetail', { total: money(placedOrder.total_value), date: formatDate(placedOrder.expected_delivery) }) }}</p>
        </div>
        <router-link to="/orders" class="confirmation-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error" role="alert">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="recommendations.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>
        <div v-if="recommendations.length === 0" class="empty-state">
          {{ t('restocking.noRecommendations') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.gap') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.cost') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in recommendations" :key="item.item_sku">
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ translateProductName(item.item_name) }}</td>
                <td>{{ item.gap }}</td>
                <td><strong>{{ item.quantity }}</strong></td>
                <td>{{ moneyWithDecimals(item.unit_cost) }}</td>
                <td><strong>{{ moneyWithDecimals(item.cost) }}</strong></td>
                <td>{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
                <td>
                  <span :class="['badge', item.trend]">
                    {{ t(`trends.${item.trend}`) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentLocale, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const submitError = ref(null)
    const placedOrder = ref(null)

    const money = (amount) => formatCurrency(amount, currentCurrency.value)
    const moneyWithDecimals = (amount) => formatCurrencyWithDecimals(amount, currentCurrency.value, 2)

    // Items with a positive demand gap, largest gap first
    const gapItems = computed(() => {
      return forecasts.value
        .map(f => ({ ...f, gap: f.forecasted_demand - f.current_demand }))
        .filter(f => f.gap > 0 && f.unit_cost > 0)
        .sort((a, b) => b.gap - a.gap)
    })

    const totalGapCost = computed(() => {
      return gapItems.value.reduce((sum, f) => sum + f.gap * f.unit_cost, 0)
    })

    // Slider step scales with the budget range (about 1% of max, power of ten)
    const sliderStep = computed(() => {
      if (totalGapCost.value <= 0) return 1
      return Math.max(1, Math.pow(10, Math.floor(Math.log10(totalGapCost.value)) - 1))
    })

    const maxBudget = computed(() => {
      return Math.ceil(totalGapCost.value / sliderStep.value) * sliderStep.value
    })

    // Greedy allocation by gap, skipping items that cannot afford a single unit
    const recommendations = computed(() => {
      let remaining = budget.value
      const result = []
      for (const item of gapItems.value) {
        const quantity = Math.min(item.gap, Math.floor(remaining / item.unit_cost))
        if (quantity <= 0) continue
        const cost = quantity * item.unit_cost
        remaining -= cost
        result.push({ ...item, quantity, cost })
      }
      return result
    })

    const totalSpend = computed(() => recommendations.value.reduce((sum, r) => sum + r.cost, 0))
    const remainingBudget = computed(() => Math.max(0, budget.value - totalSpend.value))
    const orderLeadTime = computed(() => {
      return recommendations.value.reduce((max, r) => Math.max(max, r.lead_time_days), 0)
    })

    const formatDate = (dateString) => {
      const date = new Date(dateString)
      if (isNaN(date.getTime())) return ''
      const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
      return date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' })
    }

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        budget.value = Math.round((maxBudget.value * 0.5) / sliderStep.value) * sliderStep.value
      } catch (err) {
        error.value = 'Failed to load demand forecasts: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (recommendations.value.length === 0 || submitting.value) return
      submitting.value = true
      submitError.value = null
      placedOrder.value = null
      try {
        placedOrder.value = await api.createRestockOrder({
          items: recommendations.value.map(r => ({ sku: r.item_sku, quantity: r.quantity }))
        })
      } catch (err) {
        const detail = err.response?.data?.detail
        submitError.value = t('restocking.orderFailed') + (typeof detail === 'string' ? ': ' + detail : '')
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      loading,
      error,
      budget,
      maxBudget,
      sliderStep,
      recommendations,
      totalSpend,
      remainingBudget,
      orderLeadTime,
      submitting,
      submitError,
      placedOrder,
      money,
      moneyWithDecimals,
      formatDate,
      placeOrder,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-card {
  margin-bottom: 1.5rem;
}

.budget-amount {
  font-size: 1.25rem;
  font-weight: 600;
  color: #0f172a;
}

.budget-body {
  padding: 0.5rem 0 0.25rem;
}

.budget-slider {
  width: 100%;
  accent-color: #0f172a;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.813rem;
  color: #64748b;
  margin-top: 0.25rem;
}

.confirmation {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  color: #166534;
}

.confirmation p {
  margin: 0.25rem 0 0;
  font-size: 0.875rem;
}

.confirmation-link {
  color: #0f172a;
  font-weight: 500;
  text-decoration: underline;
  white-space: nowrap;
}

.place-order-btn {
  padding: 0.5rem 1rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #e2e8f0;
  color: #64748b;
  cursor: not-allowed;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}
</style>
