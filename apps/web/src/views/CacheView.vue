<script setup>
import ListView from '../components/ListView.vue'
</script>
<template>
  <ListView endpoint="/files/cache" title="缓存资源" subtitle="查看 data/cache 下的文件" empty-text="没有找到缓存文件。" item-kind="files" />
</template>