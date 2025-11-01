import sys
import pytest
from recognize_products import parse_product_id


@pytest.mark.parametrize("url,expected", [
    # paste more valid URLs here
    ("https://www.galaxus.ch/de/s1/product/hp-omen-x-25f-1920-x-1080-pixel-2450-monitor-12201676",
     "12201676"),
    ("https://www.galaxus.ch/de/s10/product/pampers-premium-protection-gr-5-monatsbox-152-stueck-windeln-23688428?supplier=406802&utm_source=google&utm_medium=cpc&utm_campaign=PMax:+PROD_CH_SSC_Cluster_8(C)&campaignid=20489048141&adtype=pla&adgroupid=&adid=&dgCidg=Cj0KCQjw35bIBhDqARIsAGjd-cYGkuvH6FSp4MRMwvP_Haq6JMFS3tiybpsbrADP5v6Um7CTL-JaddUaAhUIEALw_wcB&gclsrc=aw.ds&&dgCidg=Cj0KCQjw35bIBhDqARIsAGjd-cYGkuvH6FSp4MRMwvP_Haq6JMFS3tiybpsbrADP5v6Um7CTL-JaddUaAhUIEALw_wcB&gad_source=1&gad_campaignid=19973635183&gbraid=0AAAAADmCc4NmHfZ9LSEDzLz5BjgWTCACf&gclid=Cj0KCQjw35bIBhDqARIsAGjd-cYGkuvH6FSp4MRMwvP_Haq6JMFS3tiybpsbrADP5v6Um7CTL-JaddUaAhUIEALw_wcB",
     "23688428"),
    ("https://www.galaxus.de/de/s5/product/lego-millennium-falcon-75192-lego-star-wars-lego-seltene-sets-lego-7238420?utm_campaign=preisvergleich&utm_source=geizhals&utm_medium=cpc&utm_content=2705624&supplier=2705624",
     "7238420"),
])
def test_valid_urls(url, expected):
    assert parse_product_id(url) == expected

@pytest.mark.parametrize("url", [
    # paste more invalid URLs here
    "https://www.galaxus.ch/de/s1/product/apple-iphone",
    "https://www.galaxus.ch/de/s1/category/smartphones-49221234",
    "https://example.com/product/49221234",
    "",
    None,
])
def test_invalid_urls(url):
    assert parse_product_id(url or "") is None
