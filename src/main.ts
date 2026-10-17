import {
  waitForEvenAppBridge,
  TextContainerProperty,
  TextContainerUpgrade,
  CreateStartUpPageContainer,
  RebuildPageContainer,
  OsEventTypeList,
} from '@evenrealities/even_hub_sdk'

// Wait for the bridge to be ready before doing anything else.
const bridge = await waitForEvenAppBridge()

let count = 0
const render = () => `Hello from Lahacks!\n\nTap to count: ${count}\nDouble-tap to exit`

// A single text container that fills the visible canvas (576×288).
const mainText = new TextContainerProperty({
  xPosition: 0,
  yPosition: 0,
  width: 576,
  height: 288,
  borderWidth: 0,
  borderColor: 5,
  paddingLength: 4,
  containerID: 1,
  containerName: 'main',
  content: render(),
  isEventCapture: 1, // receive click events on this container
})

const result = await bridge.createStartUpPageContainer(
  new CreateStartUpPageContainer({
    containerTotalNum: 1,
    textObject: [mainText],
  }),
)

if (result !== 0) {
  // The startup page can only be created once per session. After a Vite
  // reload it already exists, so rebuild it instead.
  const rebuilt = await bridge.rebuildPageContainer(
    new RebuildPageContainer({
      containerTotalNum: 1,
      textObject: [mainText],
    }),
  )
  if (!rebuilt) console.error('createStartUpPageContainer failed:', result)
}

bridge.onEvenHubEvent((event) => {
  // Taps arrive as sysEvent (source-aware) or textEvent depending on host version.
  const input = event.textEvent ?? event.sysEvent
  if (!input) return

  switch (input.eventType) {
    case OsEventTypeList.CLICK_EVENT:
    case undefined: // SDK normalizes 0 to undefined in some cases
      count += 1
      bridge.textContainerUpgrade(new TextContainerUpgrade({
        containerID: 1,
        containerName: 'main',
        content: render(),
      }))
      break

    case OsEventTypeList.DOUBLE_CLICK_EVENT:
      // Mode 1 shows the system exit-confirmation dialog (required on the root page).
      bridge.shutDownPageContainer(1)
      break
  }
})
