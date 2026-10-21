import LoginModal from '../components/LoginModal.vue'
import type { ProductUiExtension } from './contracts'

const communityProductUi: ProductUiExtension = {
  extensionId: 'mogo.community',
  loginModal: LoginModal,
}

export default communityProductUi
