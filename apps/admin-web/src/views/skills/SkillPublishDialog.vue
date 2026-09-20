<template>
  <n-modal :show="show" preset="card" :title="t('发布 Skill 版本')" style="width:520px" @update:show="emit('update:show', $event)">
    <n-form label-placement="top"><n-form-item :label="t('版本号（留空自动递增）')"><n-input v-model:value="version" placeholder="1.0.0" /></n-form-item><n-form-item :label="t('版本说明')"><n-input v-model:value="notes" type="textarea" :rows="4" maxlength="2000" show-count /></n-form-item></n-form>
    <template #footer><n-space justify="end"><n-button @click="emit('update:show', false)">{{ t('取消') }}</n-button><n-button type="primary" :loading="busy" @click="submit"><template #icon><span class="button-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v12" /><path d="m7 8 5-5 5 5" /><path d="M5 14v5h14v-5" /></svg></span></template>{{ t('发布') }}</n-button></n-space></template>
  </n-modal>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'; import { NButton,NForm,NFormItem,NInput,NModal,NSpace,useMessage } from 'naive-ui'; import { publishSkill,type SkillItem } from '@/api/skills'; import { t } from '@/composables/i18n';
const props=defineProps<{show:boolean;skill:SkillItem|null}>(); const emit=defineEmits<{ 'update:show':[boolean]; published:[SkillItem] }>(); const version=ref(''),notes=ref(''),busy=ref(false),message=useMessage(); watch(()=>props.show,v=>{if(v){version.value='';notes.value=''}});
async function submit(){if(!props.skill)return;busy.value=true;try{const out=await publishSkill(props.skill.id,version.value,notes.value);emit('published',out.skill);emit('update:show',false);message.success(t('Skill 已发布'))}catch(e:any){message.error(e?.response?.data?.detail||t('发布失败'))}finally{busy.value=false}}
</script>
