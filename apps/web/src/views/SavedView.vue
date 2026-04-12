<script setup>
import ListView from '../components/ListView.vue'
</script>
<template>
  <ListView endpoint="/saved" title="已保存报告" subtitle="查看明确保存过的报告" empty-text="还没有已保存报告。" item-kind="saved" />
</template>