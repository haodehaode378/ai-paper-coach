import { createRouter, createWebHashHistory } from 'vue-router'

import TaskView from '../views/TaskView.vue'
import ResultsView from '../views/ResultsView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'task',
      component: TaskView
    },
    {
      path: '/results',
      name: 'results',
      component: ResultsView
    }
  ]
})

export default router
