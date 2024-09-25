# -*- coding: utf-8 -*-
"""Module for interacting with a user's youtube channel."""
import json
import logging
from typing import Dict, Iterable, List, Optional, Tuple, Union


from datetime import datetime
from urllib.parse import unquote
from re import findall

from pytube import extract, Playlist, request, YouTube
from pytube.helpers import uniqueify, cache, DeferredGeneratorList

logger = logging.getLogger(__name__)


class Channel(Playlist):
    def __init__(self, url: str, proxies: Optional[Dict[str, str]] = None):
        """Construct a :class:`Channel <Channel>`.

        :param str url:
            A valid YouTube channel URL.
        :param proxies:
            (Optional) A dictionary of proxies to use for web requests.
        """
        super().__init__(url, proxies)

        self.channel_uri = extract.channel_name(url)

        self.channel_url = (
            f"https://www.youtube.com{self.channel_uri}"
        )

        self.videos_url = self.channel_url + '/videos'
        self.shorts_url = self.channel_url + '/shorts'
        self.playlists_url = self.channel_url + '/playlists'
        self.community_url = self.channel_url + '/community'
        self.featured_channels_url = self.channel_url + '/channels'
        self.about_url = self.channel_url + '/about'

        # Possible future additions
        self._playlists_html = None
        self._shorts_html = None
        self._shorts_initial_data = None
        self._community_html = None
        self._featured_channels_html = None
        self._about_html = None
        
        self._about_page_initial_data = None

    @property
    def channel_name(self):
        """Get the name of the YouTube channel.

        :rtype: str
        """
        return self.initial_data['metadata']['channelMetadataRenderer']['title']

    @property
    def channel_id(self):
        """Get the ID of the YouTube channel.

        This will return the underlying ID, not the vanity URL.

        :rtype: str
        """
        return self.initial_data['metadata']['channelMetadataRenderer']['externalId']

    @property
    def vanity_url(self):
        """Get the vanity URL of the YouTube channel.

        Returns None if it doesn't exist.

        :rtype: str
        """
        return self.initial_data['metadata']['channelMetadataRenderer'].get('vanityChannelUrl', None)  # noqa:E501

    @property
    def html(self):
        """Get the html for the /videos page.

        :rtype: str
        """
        if self._html:
            return self._html
        self._html = request.get(self.videos_url)
        return self._html

    @property
    def playlists_html(self):
        """Get the html for the /playlists page.

        Currently unused for any functionality.

        :rtype: str
        """
        if self._playlists_html:
            return self._playlists_html
        else:
            self._playlists_html = request.get(self.playlists_url)
            return self._playlists_html

    @property
    def community_html(self):
        """Get the html for the /community page.

        Currently unused for any functionality.

        :rtype: str
        """
        if self._community_html:
            return self._community_html
        else:
            self._community_html = request.get(self.community_url)
            return self._community_html

    @property
    def featured_channels_html(self):
        """Get the html for the /channels page.

        Currently unused for any functionality.

        :rtype: str
        """
        if self._featured_channels_html:
            return self._featured_channels_html
        else:
            self._featured_channels_html = request.get(self.featured_channels_url)
            return self._featured_channels_html

    @property
    def about_html(self):
        """Get the html for the /about page.

        Currently unused for any functionality.

        :rtype: str
        """
        if self._about_html:
            return self._about_html
        else:
            self._about_html = request.get(self.about_url)
            return self._about_html

    @staticmethod
    def _extract_videos(raw_json: str) -> Tuple[List[str], Optional[str]]:
        """Extracts videos from a raw json page

        :param str raw_json: Input json extracted from the page or the last
            server response
        :rtype: Tuple[List[str], Optional[str]]
        :returns: Tuple containing a list of up to 100 video watch ids and
            a continuation token, if more videos are available
        """
        initial_data = json.loads(raw_json)
        # this is the json tree structure, if the json was extracted from
        # html
        try:
            videos = initial_data["contents"][
                "twoColumnBrowseResultsRenderer"][
                "tabs"][1]["tabRenderer"]["content"][
                "richGridRenderer"]["contents"]
        except (KeyError, IndexError, TypeError):
            try:
                # this is the json tree structure, if the json was directly sent
                # by the server in a continuation response
                important_content = initial_data[1]['response']['onResponseReceivedActions'][
                    0
                ]['appendContinuationItemsAction']['continuationItems']
                videos = important_content
            except (KeyError, IndexError, TypeError):
                try:
                    # this is the json tree structure, if the json was directly sent
                    # by the server in a continuation response
                    # no longer a list and no longer has the "response" key
                    important_content = initial_data['onResponseReceivedActions'][0][
                        'appendContinuationItemsAction']['continuationItems']
                    videos = important_content
                except (KeyError, IndexError, TypeError) as p:
                    logger.info(p)
                    return [], None

        try:
            continuation = videos[-1]['continuationItemRenderer'][
                'continuationEndpoint'
            ]['continuationCommand']['token']
            videos = videos[:-1]
        except (KeyError, IndexError):
            # if there is an error, no continuation is available
            continuation = None

        # remove duplicates
        return (
            uniqueify(
                list(
                    # only extract the video ids from the video data
                    map(
                        lambda x: (
                            f"/watch?v="
                            f"{x['richItemRenderer']['content']['videoRenderer']['videoId']}"
                        ),
                        videos
                    )
                ),
            ),
            continuation,
        )


    @property
    def shorts_html(self):
        """Get the html for the /shorts page.

        Currently unused for any functionality.

        :rtype: str
        """
        if self._shorts_html:
            return self._shorts_html
        else:
            self._shorts_html = request.get(self.shorts_url)
            return self._shorts_html
        
        
    def _paginate_shorts(
        self, until_watch_id: Optional[str] = None
    ) -> Iterable[List[str]]:
        """Parse the video links from the page source, yields the /watch?v=
        part from video link

        :param until_watch_id Optional[str]: YouTube Video watch id until
            which the playlist should be read.

        :rtype: Iterable[List[str]]
        :returns: Iterable of lists of YouTube watch ids
        """
        videos_urls, continuation = self._extract_shorts(
            json.dumps(extract.initial_data(self.shorts_html))
        )
        if until_watch_id:
            try:
                trim_index = videos_urls.index(f"/shorts/{until_watch_id}")
                yield videos_urls[:trim_index]
                return
            except ValueError:
                pass
        yield videos_urls

        # Extraction from a playlist only returns 100 videos at a time
        # if self._extract_shorts returns a continuation there are more
        # than 100 songs inside a playlist, so we need to add further requests
        # to gather all of them
        if continuation:
            load_more_url, headers, data = self._build_continuation_url(continuation)
        else:
            load_more_url, headers, data = None, None, None

        while load_more_url and headers and data:  # there is an url found
            logger.debug("load more url: %s", load_more_url)
            # requesting the next page of videos with the url generated from the
            # previous page, needs to be a post
            req = request.post(load_more_url, extra_headers=headers, data=data)
            # extract up to 100 songs from the page loaded
            # returns another continuation if more videos are available
            videos_urls, continuation = self._extract_shorts(req)
            if until_watch_id:
                try:
                    trim_index = videos_urls.index(f"/shorts/={until_watch_id}")
                    yield videos_urls[:trim_index]
                    return
                except ValueError:
                    pass
            yield videos_urls

            if continuation:
                load_more_url, headers, data = self._build_continuation_url(
                    continuation
                )
            else:
                load_more_url, headers, data = None, None, None

    def shorts_url_generator(self):
        """Generator that yields shorts URLs.

        :Yields: Short URLs
        """
        for page in self._paginate_shorts():
            for video in page:
                yield self._video_url(video)
                   
    @property
    def shorts_initial_data(self):
        """Extract the initial data from the playlist page html.

        :rtype: dict
        """
        if self._shorts_initial_data:
            return self._shorts_initial_data
        else:
            self._shorts_initial_data = extract.initial_data(self.shorts_html)
            return self._shorts_initial_data 
        
    @staticmethod
    def _extract_shorts(raw_json: str) -> Tuple[List[str], Optional[str]]:
        """Extracts videos from a raw json page

        :param str raw_json: Input json extracted from the page or the last
            server response
        :rtype: Tuple[List[str], Optional[str]]
        :returns: Tuple containing a list of up to 100 video watch ids and
            a continuation token, if more videos are available
        """
        initial_data = json.loads(raw_json)
        from json import dumps
        with open("shorts_initial_data.json", 'w', encoding='utf-8') as f:
            # dump(self.info, f, indent=4)                
            json_data = dumps(initial_data, ensure_ascii=False, indent=4)
            f.write(json_data)           
            
        # this is the json tree structure, if the json was extracted from
        # html
        try:
            videos = initial_data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][2]["tabRenderer"]["content"]["richGridRenderer"]["contents"]
        except (KeyError, IndexError, TypeError):
            try:
                # this is the json tree structure, if the json was directly sent
                # by the server in a continuation response
                important_content = initial_data[1]['response']['onResponseReceivedActions'][
                    0
                ]['appendContinuationItemsAction']['continuationItems']
                videos = important_content
            except (KeyError, IndexError, TypeError):
                try:
                    # this is the json tree structure, if the json was directly sent
                    # by the server in a continuation response
                    # no longer a list and no longer has the "response" key
                    important_content = initial_data['onResponseReceivedActions'][0][
                        'appendContinuationItemsAction']['continuationItems']
                    videos = important_content
                except (KeyError, IndexError, TypeError) as p:
                    logger.info(p)
                    return [], None

        try:
            continuation = videos[-1]['continuationItemRenderer'][
                'continuationEndpoint'
            ]['continuationCommand']['token']
            videos = videos[:-1]
        except (KeyError, IndexError):
            # if there is an error, no continuation is available
            continuation = None

        # remove duplicates
        return (
            uniqueify(
                list(
                    # only extract the video ids from the video data
                    map(
                        lambda x: (
                            f"/shorts/"
                            f"{x["richItemRenderer"]["content"]["shortsLockupViewModel"]["onTap"]["innertubeCommand"]["commandMetadata"]["webCommandMetadata"]["url"].split("/")[-1]}"
                            
                        ),
                        videos
                    )
                ),
            ),
            continuation,
        )

    @property  # type: ignore
    @cache
    def shorts_urls(self) -> DeferredGeneratorList:
        """Complete links of all the videos in channel

        :rtype: List[str]
        :returns: List of video URLs
        """
        return DeferredGeneratorList(self.shorts_url_generator())

    def shorts_generator(self):
        for url in self.shorts_urls:
            yield YouTube(url)
            
    @property
    def shorts(self) -> Iterable[YouTube]:
        """Yields YouTube objects of shorts in this channel

        :rtype: List[YouTube]
        :returns: List of YouTube
        """
        return DeferredGeneratorList(self.shorts_generator())
    
    @property
    def shorts_length(self) -> str:
        """Get the number of shorts of the YouTube channel.
        
        currently it does not return a correct value because it does not get all the urls of the channel's videos correctly 

        :rtype: str
        """
        return len(self.shorts_urls)
      
    
              
  
    @property
    def about_page_initial_data(self):
        """Get the initial data for the /about page.

        Currently unused for any functionality.

        :rtype: dict
        """
        if not self._about_page_initial_data:
            self._about_page_initial_data = extract.initial_data(self.about_html)
        return self._about_page_initial_data


    @property
    def is_a_verified_channel(self) -> bool:
        """Get the the verified badge status of the YouTube channel.
        
        :rtype: bool
        """
        try:
            _is_a_verified_channel= self.about_page_initial_data["header"]["pageHeaderRenderer"]["content"]["pageHeaderViewModel"]["title"]["dynamicTextViewModel"]["rendererContext"]["accessibilityContext"]["label"].split(", ")[1]
            if _is_a_verified_channel == "Verified":
                _is_a_verified_channel = True
        except KeyError:
            _is_a_verified_channel = False
        return _is_a_verified_channel
    
    @property
    def banner_thumbnail(self) -> Optional[str]:
        """Get the banner thumbnail of the YouTube channel.

        :rtype: Optional[str]
        """
        try:
            _banner_thumbnail_ = self.about_page_initial_data["header"]["pageHeaderRenderer"]["content"]["pageHeaderViewModel"]["banner"]["imageBannerViewModel"]["image"]["sources"]
            _banner_thumbnail = []
            
            for content in _banner_thumbnail_:
                k = f'{content["width"]}x{content["height"]}'
                v = "https://"+unquote(content["url"])
                _banner_thumbnail.append(f"{k}: {v}")
        except KeyError:
            _banner_thumbnail = None
        return _banner_thumbnail    
    
    @property
    def avatar_thumbnail(self) -> Optional[str]:
        """Get the avatar thumbnail of the YouTube channel.

        :rtype: Optional[str]
        """
        try:
            _avatar_thumbnail = self.initial_data["metadata"]["channelMetadataRenderer"]["avatar"]["thumbnails"][-1]["url"]
        except KeyError:
            _avatar_thumbnail = None
        return _avatar_thumbnail    
    
    @property
    def description(self) -> Optional[str]:
        """Get the description of the YouTube channel.

        :rtype: Optional[str]
        """
        try:
            _description = self.initial_data["metadata"]["channelMetadataRenderer"]["description"]       
        except KeyError:
            _description = None
        return _description
        
    @property
    def urls_present_in_the_channel_description(self) -> Union[List[str], int]:
        """Get the Urls present in the channel description of the YouTube channel.

        :rtype: Union[List[str], int]
        """        
        _urls = []
        if self.description:           
            pattern = "https?:\\/\\/(?:www\\.)?[-a-zA-Z0-9@:%._\\+~#=]{1,256}\\.[a-zA-Z0-9()]{1,6}\\b(?:[-a-zA-Z0-9()@:%_\\+.~#?&\\/=]*)"         
            _urls = list(set(findall(pattern, self.description)))    
        if not len(_urls):
            _urls = 0      
        return _urls
           
    @property
    def mails_present_in_the_channel_description(self) -> Union[List[str], int]:
        """Get the Mails present in the channel description of the YouTube channel.

        :rtype: Union[List[str], int]
        """           
        _mails = []
        if self.description:      
            pattern = r"\S+@\S+\.\S+"             
            _mails = [mail for mail in list(set(findall(pattern, self.description))) if not mail.startswith("http")]   
        if not len(_mails):
            _mails = 0      
        return _mails
     
    @property
    def keywords(self) -> List[str]:
        """Get the description of the YouTube channel.

        :rtype: List[str]
        """
        try:
            _keywords = self.initial_data["microformat"]["microformatDataRenderer"]["tags"] # -> List[str] or raise KeyError if there not exists tags
        except KeyError:
            _keywords = []
        return _keywords
    
    @property
    def about_page_initial_data(self):
        """Get the initial data for the /about page.

        Currently unused for any functionality.

        :rtype: dict
        """
        if not self._about_page_initial_data:
            self._about_page_initial_data = extract.initial_data(self.about_html)
        return self._about_page_initial_data
       
    @property
    def joined_date(self) -> str:
        """Get the joined date of the YouTube channel.

        :rtype: str
        """        
        try:
            _joined_date = self.about_page_initial_data["onResponseReceivedEndpoints"][0]["showEngagementPanelEndpoint"]["engagementPanel"]["engagementPanelSectionListRenderer"]["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"][0]["aboutChannelRenderer"]["metadata"]["aboutChannelViewModel"]["joinedDateText"]["content"].replace("Joined ","")      
            _joined_date = str(datetime.strptime(_joined_date, '%b %d, %Y').date())
        except KeyError:
            _joined_date = None
        return _joined_date    
    
    @property
    def channel_views(self) -> int:
        """Get the number of views of the YouTube channel.

        :rtype: int
        """        
        try:
            _channel_views = self.about_page_initial_data["onResponseReceivedEndpoints"][0]["showEngagementPanelEndpoint"]["engagementPanel"]["engagementPanelSectionListRenderer"]["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"][0]["aboutChannelRenderer"]["metadata"]["aboutChannelViewModel"]["viewCountText"]
            _channel_views = int(_channel_views.replace(",", "").replace(" views", ""))
        except KeyError:
            _channel_views = None
        return _channel_views    
    
    @property
    def country(self) -> str:
        """Get the country of the YouTube channel.

        :rtype: str
        """        
        try:
            _country = self.about_page_initial_data["onResponseReceivedEndpoints"][0]["showEngagementPanelEndpoint"]["engagementPanel"]["engagementPanelSectionListRenderer"]["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"][0]["aboutChannelRenderer"]["metadata"]["aboutChannelViewModel"]["country"]
        except KeyError:
            _country = None
        return _country    
    
    @property
    def social_links(self) -> list:
        """Get the social links of the YouTube channel.

        :rtype: dict
        """
        social_links_list = []
        try:
            social_links = self.about_page_initial_data["onResponseReceivedEndpoints"][0]["showEngagementPanelEndpoint"]["engagementPanel"]["engagementPanelSectionListRenderer"]["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"][0]["aboutChannelRenderer"]["metadata"]["aboutChannelViewModel"]["links"]
            
            for social_link in social_links:
                k = unquote(social_link["channelExternalLinkViewModel"]["title"]["content"])
                v = "https://"+unquote(social_link["channelExternalLinkViewModel"]["link"]["content"])
                social_links_list.append(f"{k}: {v}")
                
        except KeyError as e:
            social_links_list = None
            
        return social_links_list    
    
    @property
    def subscribers(self) -> int:
        """Get the number of subscribers of the YouTube channel.

        :rtype: int
        """
        try:
            _subscribers = self.about_page_initial_data["header"]["pageHeaderRenderer"]["content"]["pageHeaderViewModel"]["metadata"]["contentMetadataViewModel"]["metadataRows"][1]["metadataParts"][0]["text"]["content"].replace(" subscribers", "")     
            _subscribers = _subscribers.replace("K", "e3").replace("M", "e6").replace("No", "0")  
            _subscribers = int(float(_subscribers))    
        except KeyError:
            _subscribers = None
        return _subscribers
       
    @property
    def channel_type(self) -> str:
        """Get the type of the YouTube channel.
    
        
        Not implemented yet
        
        This metric is derived from the users 10 most recent public videos.
        Social Blade uses the channeltype that occurs most.

        :rtype: str
        """
        _channel_type = None
        return _channel_type
   

    @property
    def length(self) -> str:
        """Get the number of videos of the YouTube channel.
        
        currently it does not return a correct value because it does not get all the urls of the channel's videos correctly 

        :rtype: str
        """
        return len(self.video_urls)
   
