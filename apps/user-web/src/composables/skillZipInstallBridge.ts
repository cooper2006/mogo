export const SKILL_ZIP_INSTALL_EVENT = 'mogo:install-skill-zip';

export function openSkillZipInstaller(file?: File): void {
  window.dispatchEvent(new CustomEvent(SKILL_ZIP_INSTALL_EVENT, { detail: { file } }));
}
