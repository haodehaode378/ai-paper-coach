<script setup>
import ListView from '../components/ListView.vue'
</script>
<template>
  <ListView endpoint="/files/uploads" title="上传文件" subtitle="查看 data/uploads 下的文件" empty-text="没有找到上传文件。" item-kind="files" />
</template>