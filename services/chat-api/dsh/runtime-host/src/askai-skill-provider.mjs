import { SkillBundleMaterializer } from './skill-bundle-materializer.mjs'

const PROVIDER_NAME = 'askai-enterprise'

export class AskaiSkillProvider {
  #skills
  #byName

  constructor(skillProfile, { storageRoot, bundleGatewayUrl = '', accessToken = '' } = {}) {
    this.name = PROVIDER_NAME
    this.#skills = Object.freeze([...(skillProfile?.skills ?? [])].map(skill => Object.freeze(structuredClone(skill))))
    this.#byName = new Map(this.#skills.map(skill => [skill.name, skill]))
    this.materializer = storageRoot === undefined ? undefined : new SkillBundleMaterializer(storageRoot, { bundleGatewayUrl, accessToken })
  }

  async list() {
    return this.#skills.map(skill => ({
      name: skill.name,
      description: skill.description,
      ...(skill.when_to_use ? { whenToUse: skill.when_to_use } : {}),
      invocation: {
        modelInvocable: skill.model_invocable !== false,
        userInvocable: skill.user_invocable !== false,
      },
      source: `askai:${skill.source_scope}`,
      rank: 100,
      provider: PROVIDER_NAME,
      locator: Object.freeze({ name: skill.name, version: skill.version }),
      metadata: Object.freeze({
        sourceId: skill.source_id,
        version: skill.version,
        kind: skill.kind,
        capabilityRefs: [...(skill.capability_refs ?? [])],
      }),
    }))
  }

  async get(candidate) {
    const skill = this.#byName.get(candidate?.locator?.name)
    if (skill === undefined || candidate?.locator?.version !== skill.version) return undefined
    const hasBundle = Boolean(skill.bundle_archive_base64 || skill.bundle_archive_id)
    return {
      name: skill.name,
      description: skill.description,
      ...(skill.when_to_use ? { whenToUse: skill.when_to_use } : {}),
      invocation: {
        modelInvocable: skill.model_invocable !== false,
        userInvocable: skill.user_invocable !== false,
      },
      source: `askai:${skill.source_scope}`,
      provider: PROVIDER_NAME,
      resourceBase: hasBundle
        ? {
            kind: 'opaque',
            description: 'Read text resources with skill_resource_read using package-relative paths. In MOGO run_script code, skill_dir is the absolute package root; copy final files into output_dir for delivery.',
          }
        : { kind: 'opaque', description: `MOGO immutable Skill ${skill.version}` },
      metadata: candidate.metadata,
      content: skill.content,
    }
  }

  hasResourceBundles() {
    return this.#skills.some(skill => Boolean(skill.bundle_archive_base64 || skill.bundle_archive_id))
  }

  async readTextResource(skillName, options) {
    const skill = this.#byName.get(skillName)
    if (skill === undefined) throw new Error(`Unknown Skill: ${skillName}`)
    if (!skill.bundle_archive_base64 && !skill.bundle_archive_id) throw new Error(`Skill has no package resources: ${skillName}`)
    if (this.materializer === undefined) throw new Error('Skill package storage is unavailable')
    const resource = await this.materializer.readTextResource(skill, options.path, options)
    return { skill: skill.name, ...resource }
  }
}

export function registerAskaiSkillProvider(ctx, skillProfile, options = {}) {
  if (!Array.isArray(skillProfile?.skills) || skillProfile.skills.length === 0) return undefined
  const provider = new AskaiSkillProvider(skillProfile, options)
  return { provider, dispose: ctx.skills.registerProvider(() => provider) }
}
