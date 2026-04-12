<script setup>
import ListView from '../components/ListView.vue'
</script>

<template>
  <ListView endpoint="/saved" title="Saved Reports" subtitle="Reports explicitly saved for later review" empty-text="No saved reports yet." item-kind="saved" />
</template>