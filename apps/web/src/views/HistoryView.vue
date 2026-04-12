<script setup>
import ListView from '../components/ListView.vue'
</script>
<template>
  <ListView endpoint="/history" title="历史记录" subtitle="浏览本地保存的结果快照" empty-text="还没有历史记录。" item-kind="history" />
</template>