import { createRouter, createWebHashHistory } from 'vue-router'

import TaskView from '../views/TaskView.vue'
import ResultsView from '../views/ResultsView.vue'
import HistoryView from '../views/HistoryView.vue'
import SavedView from '../views/SavedView.vue'
import UploadsView from '../views/UploadsView.vue'
import CacheView from '../views/CacheView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'task', component: TaskView },
    { path: '/results', name: 'results', component: ResultsView },
    { path: '/history', name: 'history', component: HistoryView },
    { path: '/saved', name: 'saved', component: SavedView },
    { path: '/uploads', name: 'uploads', component: UploadsView },
    { path: '/cache', name: 'cache', component: CacheView },
  ]
})

export default router