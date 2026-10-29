<template>
  <n-modal :show="show" preset="card" :title="t('发布 Skill 版本')" style="width:560px" @update:show="emit('update:show', $event)">
    <n-form label-placement="top"><n-form-item :label="t('版本号（留空自动递增）')"><n-input v-model:value="version" placeholder="1.0.0" /></n-form-item><n-form-item :label="t('版本说明')"><n-input v-model:value="notes" type="textarea" :rows="4" maxlength="2000" show-count /></n-form-item></n-form>
    <!-- 032-eval-gate: 最近评测报告 + 试运行入口（phase1 无测试集 UI） -->
    <n-alert v-if="recent" :type="recent.passed ? 'success' : 'warning'" :title="recent.passed ? t('最近评测通过') : t('最近评测未通过')" style="margin-bottom:12px">
      <div class="eval-metrics">
        <span>引用支撑 {{ fmt(recent.metrics?.citation_support) }}</span>
        <span>拒答正确 {{ fmt(recent.metrics?.refusal_accuracy) }}</span>
        <span>任务成功 {{ fmt(recent.metrics?.task_success) }}</span>
        <span class="eval-dry">耗时 {{ recent.durationMs }}ms · {{ recent.dryRun ? t('试运行') : t('正式') }}</span>
      </div>
      <div v-if="!recent.passed && recent.blockedReason" class="eval-blocked">{{ recent.blockedReason }}</div>
    </n-alert>
    <n-alert v-else type="info" style="margin-bottom:12px">032-eval-gate：本 Skill 尚无评测报告，发布将进入 fail-closed 评测门禁（无测试集 / 样本不足 / LLM 超时都会阻断）。</n-alert>
    <template #footer>
      <n-space justify="space-between">
        <n-button :loading="dryBusy" :disabled="!props.skill" @click="dryRun">{{ t('试运行评测') }}</n-button>
        <n-space justify="end">
          <n-button @click="emit('update:show', false)">{{ t('取消') }}</n-button>
          <n-button type="primary" :loading="busy" @click="submit"><template #icon><span class="button-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v12" /><path d="m7 8 5-5 5 5" /><path d="M5 14v5h14v-5" /></svg></span></template>{{ t('发布') }}</n-button>
        </n-space>
      </n-space>
    </template>
  </n-modal>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'; import { NAlert,NButton,NForm,NFormItem,NInput,NModal,NSpace,useMessage } from 'naive-ui'; import { publishSkill,type SkillItem } from '@/api/skills'; import { dryRunEval,fetchLatestEvalReport,type EvalReport } from '@/api/skillEval'; import { t } from '@/composables/i18n';
const props=defineProps<{show:boolean;skill:SkillItem|null}>(); const emit=defineEmits<{ 'update:show':[boolean]; published:[SkillItem] }>(); const version=ref(''),notes=ref(''),busy=ref(false),dryBusy=ref(false),recent=ref<EvalReport|null>(null),message=useMessage();
watch(()=>props.show,async v=>{if(v){version.value='';notes.value='';recent.value=null;if(props.skill){try{recent.value=await fetchLatestEvalReport(props.skill.id)}catch{recent.value=null}}}});
function fmt(x:number|undefined){return x==null?'—':Math.round(x*100)+'%'}
async function dryRun(){if(!props.skill)return;dryBusy.value=true;try{const r=await dryRunEval(props.skill.id);recent.value=r;if(r.passed)message.success(t('试运行评测通过'));else message.warning(r.blockedReason||t('试运行评测未通过'))}catch(e:any){message.error(e?.response?.data?.detail?.reason||e?.response?.data?.detail||t('试运行失败'))}finally{dryBusy.value=false}}
async function submit(){if(!props.skill)return;busy.value=true;try{const out=await publishSkill(props.skill.id,version.value,notes.value);emit('published',out.skill);emit('update:show',false);message.success(t('Skill 已发布'))}catch(e:any){message.error(e?.response?.data?.detail?.reason||e?.response?.data?.detail||t('发布失败'))}finally{busy.value=false}}
</script>
<style scoped>
.eval-metrics{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--mg-text-2)}
.eval-dry{margin-left:auto;color:var(--mg-text-3)}
.eval-blocked{margin-top:6px;font-size:12px;color:var(--mg-danger-text)}
</style>