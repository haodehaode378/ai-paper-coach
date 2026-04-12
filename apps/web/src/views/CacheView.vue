<script setup>
import ListView from '../components/ListView.vue'
</script>

<template>
  <ListView endpoint="/files/cache" title="Cache Files" subtitle="Files stored under data/cache" empty-text="No cache files found." item-kind="files" />
</template>