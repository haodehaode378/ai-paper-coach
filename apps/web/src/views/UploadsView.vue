<script setup>
import ListView from '../components/ListView.vue'
</script>

<template>
  <ListView endpoint="/files/uploads" title="Uploaded Files" subtitle="Files stored under data/uploads" empty-text="No uploaded files found." item-kind="files" />
</template>