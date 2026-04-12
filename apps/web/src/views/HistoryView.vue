<script setup>
import ListView from '../components/ListView.vue'
</script>

<template>
  <ListView endpoint="/history" title="History Records" subtitle="Browse local result snapshots" empty-text="No history records yet." item-kind="history" />
</template>